# Copyright (c) 2021 - present / Neuralmagic, Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import shutil
import tempfile
import unittest

import torch
from torch.utils.data import DataLoader
from transformers import DefaultDataCollator

from compressed_tensors.quantization.utils import is_module_quantized
from parameterized import parameterized_class
from sparseml.pytorch.utils import tensors_to_device
from sparseml.transformers import (
    SparseAutoModelForCausalLM,
    SparseAutoTokenizer,
    oneshot,
)
from sparseml.transformers.finetune.data import TextGenerationDataset
from sparseml.transformers.finetune.data.data_args import DataTrainingArguments
from tests.testing_utils import requires_gpu, requires_torch


@requires_torch
@requires_gpu
@parameterized_class(
    ("recipe", "ppl_threshold"),
    [("tests/sparseml/transformers/compression/recipes/new_quant_fp8.yaml", 5000)],
)
class TestQuantizationMatches(unittest.TestCase):
    recipe = None
    ppl_threshold = None
    # TODO: use "TinyLlama/TinyLlama-1.1B-intermediate-step-1431k-3T" for nightly
    # or weekly runs, but this smaller model is better for commit testing
    model_stub = "Xenova/llama2.c-stories15M"
    dataset = "ultrachat-200k"
    output = "tiny_llama_out"
    max_seq_length = 512
    weight_dtype = torch.float16
    num_eval = 64

    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp()

        cls.model = SparseAutoModelForCausalLM.from_pretrained(
            cls.model_stub, torch_dtype=cls.weight_dtype, device_map="cuda:0"
        )
        cls._run_oneshot(
            cls.model,
            cls.recipe,
            cls.dataset,
            os.path.join(cls.test_dir, cls.output),
        )

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_dir)
        del cls.model
        torch.cuda.empty_cache()

    @staticmethod
    def _run_oneshot(model, recipe, dataset, output_dir):
        num_calibration_samples = 512
        max_seq_length = 512
        pad_to_max_length = False

        oneshot(
            model=model,
            dataset=dataset,
            overwrite_output_dir=True,
            output_dir=output_dir,
            max_seq_length=max_seq_length,
            num_calibration_samples=num_calibration_samples,
            recipe=recipe,
            pad_to_max_length=pad_to_max_length,
            clear_sparse_session=True,
            splits={"calibration": "train_gen[:5%]"},
        )

    def _get_quant_info(self, model):
        quant_info_weights = {}
        quant_info_inputs = {}
        for name, module in model.named_modules():
            if is_module_quantized(module):
                if module.quantization_scheme.weights is not None:
                    quant_info_weights[name] = (
                        module.weight_scale,
                        module.weight_zero_point,
                        module.weight,
                    )

                if module.quantization_scheme.input_activations is not None:
                    is_dynamic = module.quantization_scheme.input_activations.dynamic
                    if not is_dynamic:
                        quant_info_inputs[name] = (
                            module.input_scale,
                            module.input_zero_point,
                        )

        return quant_info_weights, quant_info_inputs

    def test_quantization_reload(self):
        model_reloaded = SparseAutoModelForCausalLM.from_pretrained(
            os.path.join(self.test_dir, self.output),
            torch_dtype="auto",
            device_map="cuda:0",
        )

        og_weights, og_inputs = self._get_quant_info(self.model)
        reloaded_weights, reloaded_inputs = self._get_quant_info(model_reloaded)

        for name, (o_scale, o_zp, o_weight) in og_weights.items():
            n_scale, n_zp, n_weight = reloaded_weights[name]
            assert o_scale.dtype == n_scale.dtype == self.weight_dtype
            assert torch.equal(o_scale, n_scale)
            assert o_zp.dtype == n_zp.dtype == torch.float8_e4m3fn
            assert torch.equal(o_zp, n_zp)

            # we don't expect an exact match here because o_weight still has the
            # original weight and n_weight has been fake_quantized
            assert n_weight.dtype == o_weight.dtype == self.weight_dtype

        for name, (o_scale, o_zp) in og_inputs.items():
            n_scale, n_zp = reloaded_inputs[name]
            assert o_scale.dtype == n_scale.dtype == self.weight_dtype
            assert torch.equal(o_scale, n_scale)
            assert o_zp.dtype == n_zp.dtype == torch.float8_e4m3fn
            assert torch.equal(o_zp, n_zp)

    def _get_dataloader(self, data_args, tokenizer):
        dataset_manager = TextGenerationDataset.load_from_registry(
            data_args.dataset,
            data_args=data_args,
            split="train_gen[:5%]",
            tokenizer=tokenizer,
        )
        calib_dataset = dataset_manager.tokenize_and_process(
            dataset_manager.get_raw_dataset()
        )
        data_loader = DataLoader(
            calib_dataset,
            batch_size=1,
            collate_fn=DefaultDataCollator(),
            sampler=torch.utils.data.RandomSampler(calib_dataset),
        )

        return data_loader

    @torch.no_grad()
    def test_perplexity(self):
        tokenizer = SparseAutoTokenizer.from_pretrained(self.model_stub)
        data_args = DataTrainingArguments(
            dataset="ultrachat-200k",
            max_seq_length=self.max_seq_length,
        )
        dataloader = self._get_dataloader(data_args, tokenizer)

        total_ppl = 0.0
        total_non_nan = 0
        for idx, sample in enumerate(dataloader):
            if idx >= self.num_eval:
                break
            output = self.model(**tensors_to_device(sample, "cuda:0"))
            if torch.isnan(output.loss):
                continue
            total_ppl += torch.exp(output.loss).item()
            total_non_nan += 1

        avg_ppl = total_ppl / total_non_nan
        assert avg_ppl <= self.ppl_threshold
