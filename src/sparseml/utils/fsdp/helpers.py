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

import logging
import operator
from pathlib import Path
from typing import Optional, Union


try:
    from torch.distributed.fsdp import (
        FullStateDictConfig,
        FullyShardedDataParallel,
        StateDictType,
    )
except ImportError:
    FullyShardedDataParallel = None

import torch
from torch.nn import Module

from sparseml.core.model import ModifiableModel
from sparseml.pytorch.model_load.helpers import save_model_and_recipe
from sparseml.utils.pytorch import set_layer


__all__ = [
    "is_fsdp_model",
    "maybe_get_wrapped",
    "set_wrapped_model",
    "unwrap_and_export_model",
    "save_pretrained_fsdp",
    "get_fsdp_parent",
    "find_and_move_state_dicts_to_cpu",
]

_LOGGER = logging.getLogger(__name__)


def is_fsdp_model(model: Module) -> bool:
    """
    Check if a model instance is wrapped by FSDP

    :param model: pytorch model to check
    :return: True if module is wrapped, False otherwise
    """
    if not FullyShardedDataParallel:
        return False

    return isinstance(model, FullyShardedDataParallel)


def maybe_get_wrapped(model: Union[ModifiableModel, Module]) -> Module:
    """
    Given a model that may or may not have a distributed wrapper, return the underlying
    wrapped model.

    :param model: input model to get wrapped model from
    :returns: wrapped model
    """
    if isinstance(model, ModifiableModel):
        model = model.model  # get the inner PyTorch model

    if is_fsdp_model(model=model):
        return model._fsdp_wrapped_module
    return model


def set_wrapped_model(model: ModifiableModel, wrapped_model: Module):
    """
    Given a model that may or may not have a distributed wrapper, set the underlying
    wrapped model.

    :param input_model: input model to be updated
    :param updated_wrapped: model to inject into input_model
    """
    if is_fsdp_model(model.model):
        model.model._fsdp_wrapped_module = wrapped_model
    else:
        model.model = wrapped_model


def unwrap_and_export_model(model, accelerator, output_dir, tokenizer):
    """
    Recursively unwraps an FSDP model, then saves the unwrapped model and the
    currently active recipe to disk

    :param model: model to unwrap
    :param accelerator: Accelerator instance used to perform unwrapping
    :param output_dir: where to save output model
    :param tokenizer: tokenizer used by the model
    """
    full_state_dict_config = FullStateDictConfig(offload_to_cpu=True, rank0_only=True)
    with FullyShardedDataParallel.state_dict_type(
        model,
        StateDictType.FULL_STATE_DICT,
        full_state_dict_config,
    ):
        unwrapped_model = accelerator.unwrap_model(model)
        for name, module in unwrapped_model.named_modules():
            if isinstance(module, FullyShardedDataParallel):
                set_layer(name, accelerator.unwrap_model(module), unwrapped_model)

        save_model_and_recipe(
            model=unwrapped_model,
            save_path=output_dir,
            tokenizer=tokenizer,
        )


def find_and_move_state_dicts_to_cpu(output_dir: str):
    """
    Looks for state dicts in the output directory and overwrites them
    with cpu state dicts.

    this is needed for quantized models trained with FSDP as the state dict
    contains device information, which can cause issues when loading the model
    using transformers AutoModel.from_pretrained(...) if the device information
    is not removed, assumes the state dicts are named pytorch_model*.bin
    """

    for model_file in Path(output_dir).rglob("pytorch_model*.bin"):
        loaded_dict = torch.load(model_file, map_location="cpu")
        for key, value in loaded_dict.items():
            if isinstance(value, torch.Tensor):
                loaded_dict[key] = value.cpu()

        torch.save(loaded_dict, model_file)
        _LOGGER.info(f"Moved state dict {model_file} to cpu")


def save_pretrained_fsdp(model, accelerator, output_dir, save_safetensors: bool = True):
    full_state_dict_config = FullStateDictConfig(offload_to_cpu=True, rank0_only=True)
    """
    Gathers the full FSDP state dict of the model onto rank0 GPU, then uses it to save
    the pretrained FSDP model to disk

    :param model: model to save
    :param accelerator: Accelerator instance used to perform unwrapping
    :param output_dir: where to save output model
    :param save_safetensors: True to safe in safetensors format, otherwise .bin
    """
    with FullyShardedDataParallel.state_dict_type(
        model, StateDictType.FULL_STATE_DICT, full_state_dict_config
    ):
        state_dict = accelerator.get_state_dict(model, unwrap=False)

    accelerator.unwrap_model(model).save_pretrained(
        output_dir,
        is_main_process=accelerator.is_main_process,
        save_function=accelerator.save,
        state_dict=state_dict,
        safe_serialization=save_safetensors,
    )


def get_fsdp_parent(layer_name: str, model: Module) -> Optional[Module]:
    """
    Gets the closest parent of layer_name that is wrapped by FSDP. If no FSDP wrapper
    is found just return None

    :param layer_name: layer name in model to get parent of
    :model: pytorch module to search through
    :return: FSDP wrapped parent of layer_name if available, otherwise None
    """
    if not is_fsdp_model(model):
        return None

    parent_name = layer_name
    parent = operator.attrgetter(parent_name)(model)
    while not isinstance(parent, FullyShardedDataParallel):
        if len(parent_name) == 0:  # we've reached the root module and its not FSDP
            # this should never get hit because we check for an FSDP root above
            # but while statements without a backup are too scary
            return None
        parent_name = ".".join(parent_name.split(".")[:-1])
        parent = operator.attrgetter(parent_name)(model)

    return parent
