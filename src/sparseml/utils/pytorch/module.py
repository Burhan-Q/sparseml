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

"""
Utility / helper functions
"""

import re
from typing import Dict, List, Tuple, Union

import torch
from packaging import version
from torch.nn import Linear, Module, Parameter
from torch.nn.modules.conv import _ConvNd


try:
    quant_err = None
    from torch.nn.qat import Conv2d as QATConv2d
    from torch.nn.qat import Linear as QATLinear
    from torch.quantization import QuantWrapper
except Exception as _err:
    quant_err = _err
    QuantWrapper = None
    QATLinear = None
    QATConv2d = None

try:
    from torch.nn.qat import Conv3d as QATConv3d
except Exception as _err:
    quant_conv3d_err = _err
    QATConv3d = None


try:
    from transformers.modeling_utils import Conv1D as TransformerConv1D
except Exception as _err:
    gpt_conv1d_err = _err
    TransformerConv1D = None


__all__ = [
    "match_targets",
    "get_default_params",
    "match_layers_params",
    "get_layers",
    "get_layer",
    "set_layer",
    "get_params",
    "get_param",
    "set_param",
    "get_terminal_layers",
    "get_prunable_layers",
    "get_quantizable_layers",
]


_PARSED_TORCH_VERSION = version.parse(torch.__version__)


ALL_TARGET = "__ALL__"
ALL_PRUNABLE_TARGET = "__ALL_PRUNABLE__"
ALL_QUANTIZABLE_TARGET = "__ALL_QUANTIZABLE__"


def match_targets(name: str, targets: Union[str, List[str]]) -> Tuple[bool, int]:
    if isinstance(targets, str):
        targets = [targets]

    for index, target in enumerate(targets):
        if target[:3] == "re:":
            pattern = target[3:]
            if re.match(pattern, name):
                return True, index
        elif name == target:
            return True, index

    return False, -1


def get_default_params(layers: Dict[str, Module]) -> Dict[str, Parameter]:
    params = {}
    for name, layer in layers.items():
        for param_name, param in layer.named_parameters():
            if param_name == "weight":
                params[name] = param
                break
    return params


def match_layers_params(
    targets: Union[str, List[str]], module: Module, params: bool = False
) -> Dict[str, Union[Module, Parameter]]:
    if targets == ALL_TARGET:
        values = get_terminal_layers(module)

        return values if not params else get_default_params(values)

    if targets == ALL_PRUNABLE_TARGET:
        values = get_prunable_layers(module)

        return values if not params else get_default_params(values)

    if targets == ALL_QUANTIZABLE_TARGET:
        values = get_quantizable_layers(module)

        return values if not params else get_default_params(values)

    if isinstance(targets, str):
        targets = [targets]

    resolved = {}
    targets_found = [False for _ in range(len(targets))]

    for name, layer in module.named_modules():
        match, match_index = match_targets(name, targets)
        if match and not params:
            targets_found[match_index] = True
            resolved[name] = layer

        for param_name, param in layer.named_parameters():
            if "." in param_name:  # skip parameters of nested layers
                continue

            param_match, param_match_index = match_targets(
                f"{name}.{param_name}", targets
            )
            if param_match:
                targets_found[param_match_index] = True
                resolved[f"{name}"] = layer if not params else param

    missed = [target for found, target in zip(targets_found, targets) if not found]
    if len(missed) > 0:
        raise ValueError(f"Could not find targets {missed} in module {module}")

    return resolved


def get_layers(targets: Union[str, List[str]], module: Module) -> Dict[str, Module]:
    return match_layers_params(targets, module)


def get_layer(target: str, module: Module) -> Tuple[str, Module]:
    layers = get_layers(target, module)
    if len(layers) != 1:
        raise ValueError(f"Expected 1 layer for target {target}, found {len(layers)}")
    name, layer = next(iter(layers.items()))

    return name, layer


def set_layer(target: str, layer: Module, module: Module) -> Module:
    parent_target = ".".join(target.split(".")[:-1])
    parent_layer = get_layer(parent_target, module)[1]
    old_layer = getattr(parent_layer, target.split(".")[-1])
    setattr(parent_layer, target.split(".")[-1], layer)

    return old_layer


def get_params(targets: Union[str, List[str]], module: Module) -> Dict[str, Parameter]:
    return match_layers_params(targets, module, params=True)


def get_param(target: str, module: Module) -> Tuple[str, Parameter]:
    params = get_params(target, module)
    if len(params) != 1:
        raise ValueError(
            f"Expected 1 parameter for target {target}, found {len(params)}"
        )
    name, param = next(iter(params.items()))

    return name, param


def set_param(target: str, param: Parameter, module: Module) -> Parameter:
    layer_name, param_name = target.rsplit(".", 1)
    layer = get_layer(layer_name, module)[1]
    old_param = getattr(layer, param_name)
    setattr(layer, param_name, param)

    return old_param


def get_terminal_layers(module: Module) -> Dict[str, Module]:
    terminal = {}

    for name, layer in module.named_modules():
        if len(list(layer.named_modules())) > 1:
            continue

        terminal[name] = layer

    return terminal


def get_prunable_layers(module: Module) -> Dict[str, Module]:
    prunable = {}

    for name, layer in module.named_modules():
        if (
            isinstance(layer, Linear)
            or isinstance(layer, _ConvNd)
            or (QATLinear and isinstance(layer, QATLinear))
            or (QATConv2d and isinstance(layer, QATConv2d))
            or (QATConv3d and isinstance(layer, QATConv3d))
            or (TransformerConv1D and isinstance(layer, TransformerConv1D))
        ):
            prunable[name] = layer

    return prunable


def get_quantizable_layers(module: Module) -> Dict[str, Module]:
    if QATLinear is None:
        raise ImportError(
            "PyTorch version is not setup for Quantization. "
            "Please install a QAT compatible version of PyTorch"
        )

    quantizable = {}

    for name, layer in module.named_modules():
        if isinstance(layer, Linear) or isinstance(layer, _ConvNd):
            quantizable[name] = layer

    return quantizable
