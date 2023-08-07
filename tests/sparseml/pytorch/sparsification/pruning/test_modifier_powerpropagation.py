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
from collections import OrderedDict, namedtuple
from typing import List

import pytest
from torch import Tensor
from torch.nn import Module, ReLU, Sequential, Sigmoid

from sparseml.pytorch.models import (
    PowerPropagatedConv2d,
    PowerPropagatedLinear,
    convert_to_powerpropagation,
)
from sparseml.pytorch.sparsification.pruning import PowerpropagationModifier
from tests.sparseml.pytorch.helpers import LinearNet
from tests.sparseml.pytorch.sparsification.pruning.helpers import (
    state_dict_save_load_test,
)
from tests.sparseml.pytorch.sparsification.test_modifier import (
    ScheduledModifierTest,
    create_optim_adam,
    create_optim_sgd,
)


from tests.sparseml.pytorch.helpers import (  # noqa isort:skip
    test_epoch,
    test_loss,
    test_steps_per_epoch,
)


LayerDesc = namedtuple(
    "LayerDesc", ["name", "input_size", "output_size", "bias", "alpha"]
)


class PowerPropagatedLinearNet(Module):
    _LAYER_DESCS = None

    @staticmethod
    def layer_descs() -> List[LayerDesc]:
        if PowerPropagatedLinearNet._LAYER_DESCS is None:
            PowerPropagatedLinearNet._LAYER_DESCS = []
            model = PowerPropagatedLinearNet()

            for name, layer in model.named_modules():
                if not isinstance(layer, Linear):
                    continue

                PowerPropagatedLinearNet._LAYER_DESCS.append(
                    LayerDesc(
                        name,
                        [layer.in_features],
                        [layer.out_features],
                        layer.bias is not None,
                        layer.alpha,
                    )
                )

        return PowerPropagatedLinearNet._LAYER_DESCS

    def __init__(self):
        super().__init__()
        self.seq = Sequential(
            OrderedDict(
                [
                    ("fc1", PowerPropagatedLinear(8, 16, bias=True)),
                    ("fc2", PowerPropagatedLinear(16, 32, bias=True)),
                    (
                        "block1",
                        Sequential(
                            OrderedDict(
                                [
                                    ("fc1", PowerPropagatedLinear(32, 16, bias=True)),
                                    ("fc2", PowerPropagatedLinear(16, 8, bias=True)),
                                ]
                            )
                        ),
                    ),
                ]
            )
        )

    def forward(self, inp: Tensor):
        return self.seq(inp)


@pytest.mark.skipif(
    os.getenv("NM_ML_SKIP_PYTORCH_TESTS", False),
    reason="Skipping pytorch tests",
)
@pytest.mark.parametrize(
    "modifier_lambda",
    [
        lambda: PowerpropagationModifier(
            start_epoch=0,
            end_epoch=10,
            params=["re:.*weight"],
            alpha=2.0,
        ),
        lambda: PowerpropagationModifier(
            params=["seq.fc1.weight"],
            start_epoch=10.0,
            end_epoch=25.0,
            alpha=3.0,
        ),
    ],
    scope="function",
)
@pytest.mark.parametrize("model_lambda", [PowerPropagatedLinearNet], scope="function")
@pytest.mark.parametrize(
    "optim_lambda",
    [create_optim_sgd, create_optim_adam],
    scope="function",
)
class TestPowerpropagationModifier(ScheduledModifierTest):
    def test_lifecycle(
        self,
        modifier_lambda,
        model_lambda,
        optim_lambda,
        test_steps_per_epoch,  # noqa: F811
    ):
        modifier = modifier_lambda()
        model = model_lambda()
        optimizer = optim_lambda(model)
        self.initialize_helper(modifier, model)

        # check sparsity is not set before
        if modifier.start_epoch >= 0:
            for epoch in range(int(modifier.start_epoch)):
                assert not modifier.update_ready(epoch, test_steps_per_epoch)

        epoch = int(modifier.start_epoch) if modifier.start_epoch >= 0 else 0.0
        assert modifier.update_ready(epoch, test_steps_per_epoch)
        modifier.scheduled_update(model, optimizer, epoch, test_steps_per_epoch)

        if modifier.end_epoch >= 0:
            epoch = int(modifier.end_epoch)
            assert modifier.update_ready(epoch, test_steps_per_epoch)
            modifier.scheduled_update(model, optimizer, epoch, test_steps_per_epoch)

            for epoch in range(
                int(modifier.end_epoch) + 1, int(modifier.end_epoch) + 6
            ):
                assert not modifier.update_ready(epoch, test_steps_per_epoch)

    def test_state_dict_save_load(
        self,
        modifier_lambda,
        model_lambda,
        optim_lambda,
        test_steps_per_epoch,  # noqa: F811
    ):
        state_dict_save_load_test(
            self,
            modifier_lambda,
            model_lambda,
            optim_lambda,
            test_steps_per_epoch,
            False,
        )


@pytest.mark.skipif(
    os.getenv("NM_ML_SKIP_PYTORCH_TESTS", False),
    reason="Skipping pytorch tests",
)
def test_powerpropagation_yaml():
    start_epoch = 5.0
    end_epoch = 15.0
    params = ["re:.*weight"]
    alpha = 1.5
    yaml_str = f"""
    !PowerpropagationModifier
        start_epoch: {start_epoch}
        end_epoch: {end_epoch}
        params: {params}
        alpha: {alpha}
    """
    yaml_modifier = PowerpropagationModifier.load_obj(
        yaml_str
    )  # type: PowerpropagationModifier
    serialized_modifier = PowerpropagationModifier.load_obj(
        str(yaml_modifier)
    )  # type: PowerpropagationModifier
    obj_modifier = PowerpropagationModifier(
        start_epoch=start_epoch, end_epoch=end_epoch, params=params, alpha=alpha
    )

    assert isinstance(yaml_modifier, PowerpropagationModifier)
    assert (
        yaml_modifier.start_epoch
        == serialized_modifier.start_epoch
        == obj_modifier.start_epoch
    )
    assert (
        yaml_modifier.end_epoch
        == serialized_modifier.end_epoch
        == obj_modifier.end_epoch
    )
    assert yaml_modifier.params == serialized_modifier.params == obj_modifier.params
