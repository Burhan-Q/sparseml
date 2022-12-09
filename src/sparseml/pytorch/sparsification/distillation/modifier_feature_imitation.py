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
Modifier for performing knowledge distillation via feature imitation.
"""

import logging
from typing import Any, Callable, List, Optional, Union, Tuple

import torch
from torch.nn import Module

from sparseml.optim import ModifierProp
from sparseml.pytorch.sparsification.distillation.modifier_distillation_base import (
    BaseDistillationModifier,
)
from sparseml.pytorch.sparsification.modifier import PyTorchModifierYAML
from sparseml.pytorch.utils import BaseLogger
from sparseml.pytorch.sparsification.distillation.helper import *


__all__ = [
    "FeatureImitationModifier",
]

_LOGGER = logging.getLogger(__name__)

@PyTorchModifierYAML()
class FeatureImitationModifier(BaseDistillationModifier):
    """
    Adds a knowledge distillation loss based on the feature imitation loss.
    A distillation_teacher module may be provided as a kwarg to
    the Manager initialization and loss_update(loss) must be called before any
    backwards pass in the integrated training flow.
    If no teacher model is provided, then self-distillation will be used.
    The feature difference between teacher and student can be weighted spatially
    by a weighing function.

    | Sample yaml:
    |   !FeatureImitationModifier
    |       start_epoch: 0.0
    |       gain: 2.0
    |       number_of_classes: 80
    |       student_features: [64, 128, 256]
    |       teacher_features: [128, 256, 512]

    :param number_of_classes: Number of classes
    :param student_features: List containing the number of features at each layer
        of the student model
    :param teacher_features: List containing the number of features at each layer
        of the teacher model
    :param start_epoch: The epoch to start the modifier at
    :param end_epoch: The epoch to end the modifier at
    :param distill_output_keys: List of keys for the module outputs to use for
        distillation if multiple outputs are present. None or empty list defaults
        to using all available outputs
    :param teacher_input_keys: List of keys to filter the inputs by before
        passing into the teacher. None or empty list defaults to using
        all available inputs
    :param update_frequency:
    :param gain: How much to weight the distillation loss. Default is 1.5
    :param output_format: Format for output tensors following this convention:
        ("b"=batch size, "a"=anchors, "x"=horizontal tiles, "y"=vertical tiles,
         "o"=outputs)
    :param feature_format: Format for feature tensors following this convention:
        ("b"=batch size, "x"=horizontal tiles, "y"=vertical tiles, "o"=outputs)
    :param weight_function: Optional string to identify function to weight the
        difference between teacher and student feature
    :imitation_mask_anchors: Optional List of Tuples of two floats to specify
        preset anchor box locations for the imitation mask weighting method
    """

    def __init__(
        self,
        number_of_classes: int,
        student_features: List[int],
        teacher_features: List[int],
        gain: float,
        student_feature_names: List[str],
        teacher_feature_names: Optional[List[str]] = None,
        start_epoch: float = -1.0,
        end_epoch: float = -1.0,
        distill_output_keys: Optional[List[Any]] = None,
        teacher_input_keys: Optional[List[Any]] = None,
        update_frequency: float = -1.0,
        output_format: str = "bayxo",
        feature_format: str = "boyx",
        weight_function: Optional[str] = None,
        project_features: bool = True,
        anchors: Optional[List[List[int]]] = None, # [[10,13, 16,30, 33,23], [30,61, 62,45, 59,119], [116,90, 156,198, 373,326]]
        strides: Optional[List[int]] = None,       # [8, 16, 32]
        imitation_mask_anchors: Optional[List[Tuple[float]]] = None,

    ):
        super().__init__(
            start_epoch=start_epoch,
            end_epoch=end_epoch,
            distill_output_keys=distill_output_keys,
            teacher_input_keys=teacher_input_keys,
            update_frequency=update_frequency,
        )
        self.number_of_classes = number_of_classes
        self.student_features = student_features
        self.teacher_features = teacher_features
        self.gain = gain
        self.student_feature_names = student_feature_names
        self.teacher_feature_names = teacher_feature_names
        self.output_format = output_format
        self.feature_format = feature_format
        self.weight_function = weight_function
        self._student_feature_tensors = None
        self._teacher_feature_tensors = None
        self._student_handles = None
        self._teacher_handles = None
        self.imitation_mask_anchors = [(1.3221, 1.73145), (3.19275, 4.00944), (5.05587, 8.09892), (9.47112, 4.84053),
                                       (11.2364, 10.0071)]
        self._set_compute_weight()
        self.project_features = project_features
        if self.project_features:
            self._initialize_projection()
            self._registered_parameters = False

    @ModifierProp()
    def number_of_classes(self) -> int:
        """
        :return: how much to weight the distillation loss vs the base loss
            (e.g. hardness of 0.6 will return 0.6 * distill_loss + 0.4 * base_loss)
        """
        return self._number_of_classes

    @number_of_classes.setter
    def number_of_classes(self, value: int):
        """
        :params value: how much to weight the distillation loss vs the base loss
            (e.g. hardness of 0.6 will return 0.6 * distill_loss + 0.4 * base_loss)
        """
        self._number_of_classes = value

    @ModifierProp()
    def student_features(self) -> List[int]:
        return self._student_features

    @student_features.setter
    def student_features(self, value: List[int]):
        self._student_features = value

    @ModifierProp()
    def teacher_features(self) -> List[int]:
        return self._teacher_features

    @teacher_features.setter
    def teacher_features(self, value: List[int]):
        self._teacher_features = value

    @ModifierProp()
    def gain(self) -> float:
        """
        :return: how much to weight the distillation loss
        """
        return self._gain

    @gain.setter
    def gain(self, value: float):
        """
        :params value: how much to weight the distillation loss
        """
        self._gain = value

    @ModifierProp()
    def student_feature_names(self) -> List[str]:
        return self._student_feature_names

    @student_feature_names.setter
    def student_feature_names(self, value: List[str]):
        self._student_feature_names = value

    @ModifierProp()
    def teacher_feature_names(self) -> List[str]:
        if self._teacher_feature_names is None:
            return self._student_feature_names
        else:
            return self._teacher_feature_names

    @teacher_feature_names.setter
    def teacher_feature_names(self, value: List[str]):
        self._teacher_feature_names = value

    @ModifierProp()
    def output_format(self) -> str:
        return self._output_format

    @output_format.setter
    def output_format(self, value: str):
        self._output_format = value

    @ModifierProp()
    def feature_format(self) -> str:
        return self._feature_format

    @feature_format.setter
    def feature_format(self, value: str):
        self._feature_format = value

    @ModifierProp()
    def weight_function(self) -> str:
        return self._weight_function

    @weight_function.setter
    def weight_function(self, value: str):
        self._weight_function = value

    @ModifierProp(serializable=False)
    def output_class_dimension(self) -> int:
        return self.output_format.index("o")

    @ModifierProp(serializable=False)
    def output_anchor_dimension(self) -> int:
        return self.output_format.index("a")

    @ModifierProp(serializable=False)
    def feature_dimension(self) -> int:
        return self.feature_format.index("o")

    @ModifierProp(serializable=False)
    def number_of_layers(self) -> int:
        return len(self.student_features)

    @ModifierProp(serializable=False)
    def projection(self) -> List[Module]:
        return self._projection

    @projection.setter
    def projection(self, value: List[Module]):
        self._projection = value

    @ModifierProp()
    def project_features(self) -> bool:
        return self._project_features

    @project_features.setter
    def project_features(self, value: bool):
        self._project_features = value
   
    @ModifierProp()
    def imitation_mask_anchors(self) -> List[Tuple[float]]:
        return self._imitation_mask_anchors

    @imitation_mask_anchors.setter
    def imitation_mask_anchors(self, value: List[Tuple[float]]):
        self._imitation_mask_anchors = value

    @ModifierProp(serializable=False)
    def compute_weight(self) -> Callable:
        weight_methods = {
            "prediction": self._weight_prediction,
            "imitation_mask": self._weight_imitation_mask,
        }
        if self.weight_function in weight_methods:
            return weight_methods.get(self.weight_function, None)

    @compute_weight.setter
    def compute_weight(self, value: Callable):
        self._compute_weight = value

    def initialize(
        self,
        module: Module,
        epoch: float = 0,
        loggers: Optional[List[BaseLogger]] = None,
        distillation_teacher: Union[Module, str] = "disable",
        **kwargs,
    ):
        """
        Store the teacher model for distillation if provided
        :param module: the PyTorch model/module to modify
        :param epoch: The epoch to initialize the modifier and module at.
            Defaults to 0 (start of the training process)
        :param loggers: Optional list of loggers to log the modification process to
        :param distillation_teacher: teacher module to perform knowledge distillation
            with. If not provided, self distillation will be used with a teacher
             from a copy of the given module at the start epoch. If given string
             "disable" this modifier will not apply distillation of any kind,
             even in the active epoch range
        :param kwargs: Optional kwargs to support specific arguments
            for individual modifiers.
        """
        super().initialize(module, epoch, loggers, distillation_teacher, **kwargs)

        if isinstance(distillation_teacher, Module):
            self._student_feature_tensors = {}
            self._teacher_feature_tensors = {}

            def cache_output(layer_name, outputs):
                def forward_hook_fn(layer, inp, out):
                    outputs[layer_name] = out
                return forward_hook_fn

            def find_layers(layer_module, layer_names, cached_layers, name=""):
                if name in layer_names:
                    cached_layers[name] = layer_module
                for layer_module, child in layer_module.named_children():
                    find_layers(
                        child,
                        layer_names,
                        cached_layers,
                        name + "." + layer_module if name != "" else layer_module,
                    )

            cached_student_layers = {}
            cached_teacher_layers = {}
            find_layers(module, self.student_feature_names, cached_student_layers)
            find_layers(distillation_teacher, self.teacher_feature_names, cached_teacher_layers)

            self._student_handles = []
            self._teacher_handles = []
            for layer_name in cached_student_layers:
                self._student_handles.append(
                    cached_student_layers[layer_name].register_forward_hook(
                        cache_output(layer_name, self._student_feature_tensors)
                    )
                )

            for layer_name in cached_teacher_layers:
                self._student_handles.append(
                    cached_teacher_layers[layer_name].register_forward_hook(
                        cache_output(layer_name, self._teacher_feature_tensors)
                    )
                )

            self._teacher = distillation_teacher
        else:
            raise ValueError(
                "unrecognized value for distillation_modifier given of "
                f"{distillation_teacher}. "
                "To disable set to 'disable' and for self attention set to 'self'"
            )

    def finalize(
        self, module: Optional[Module] = None, reset_loggers: bool = True, **kwargs
    ):
        """
        Cleans up any state and hooks
        :param module: The model/module to finalize the modifier for.
            Marked optional so state can still be cleaned up on delete,
            but generally should always be passed in.
        :param reset_loggers: True to remove any currently attached loggers (default),
            False to keep the loggers attached.
        :param kwargs: Optional kwargs to support specific arguments
            for individual modifiers.
        """
        super().finalize(module, reset_loggers, **kwargs)
        self._student_handles.remove()
        self._teacher_handles.remove()
        self._student_handles = None
        self._teacher_handles = None
        self._student_feature_tensors = None
        self._teacher_feature_tensors = None

    def compute_distillation_loss(self, student_outputs, teacher_outputs, optimizer, student_labels,
                        teacher_labels):
        if self.project_features and not self._registered_parameters:
            student_features = self._student_feature_tensors[self.student_feature_names[0]]
            self._projection = [p.to(student_features.device) for p in self._projection]
            parameters = [p.weight for p in self._projection]
            optimizer.add_param_group({'params': parameters})
            self._registered_parameters = True

        distillation_loss = 0.0
        for layer in range(self.number_of_layers):
            student_features = self._student_feature_tensors[self.student_feature_names[layer]]
            teacher_features = self._teacher_feature_tensors[self.teacher_feature_names[layer]]
            if self.project_features:
                student_features = self._projection[layer](student_features.float())

            feature_difference = torch.mean(
                (student_features - teacher_features) ** 2,
                dim=self.feature_dimension,
            )

            if self.weight_function is not None:
                weight = self.compute_weight(layer, student_outputs,
                                             teacher_outputs,
                                             student_labels=student_labels,
                                             teacher_labels=teacher_labels)
            else:
                weight = 1.0

            fi_loss = torch.mean(weight * feature_difference)
            distillation_loss += fi_loss

        return distillation_loss / self.number_of_layers

    def compute_total_loss(self, loss, distillation_loss):
        return loss + self.gain * distillation_loss

    def _initialize_projection(self):
        projection = []
        for layer in range(self.number_of_layers):
            projection.append(
                torch.nn.Conv2d(
                    in_channels=self.student_features[layer],
                    out_channels=self.teacher_features[layer],
                    kernel_size=1,
                    bias=False,
                )
            )
        self._projection = projection

    def _set_compute_weight(self):
        weight_methods = {"prediction": self._weight_prediction,
                          "imitation_mask": self._weight_imitation_mask}
        if self.weight_function is None:
            self.compute_weight = None
        else:
            self.compute_weight = weight_methods[self.weight_function]

    def _get_scores(self, outputs):
        _, scores = torch.split(
            outputs, (5, self.number_of_classes), dim=self.output_class_dimension
        )
        return torch.sigmoid(scores)

    def _weight_prediction(self, layer, student_outputs, teacher_outputs, **kwargs):
        """
        Prediction-guided weight for feature imitation.
        Adapted from the paper "Knowledge Distillation for Object Detection
        via Rank Mimicking and Prediction-guided Feature Imitation"
        (https://arxiv.org/abs/2112.04840)
        """

        student_class_scores = self._get_scores(student_outputs[layer])
        teacher_class_scores = self._get_scores(teacher_outputs[layer])

        weight = torch.mean(
            (student_class_scores - teacher_class_scores) ** 2,
            dim=(self.output_anchor_dimension, self.output_class_dimension),
        )

        return weight

    def _weight_imitation_mask(self, layer, student_outputs, teacher_outputs,
                               student_labels, teacher_labels, iou_factor=0.5):
        """
        IoU comparisoon based weight for feature imitation
        Adapted from the paper "Distilling Object Detectors with Fine-grained Feature Imitation"
        (https://arxiv.org/abs/1906.03609)
        """
        teacher_features = teacher_outputs[layer]

        out_size = teacher_features.size(2)
        batch_size = teacher_features.size(0)
        device = teacher_labels.device

        mask_batch = torch.zeros([batch_size, out_size, out_size])

        if not len(teacher_labels):
            return mask_batch

        gt_boxes = [[] for i in range(batch_size)]
        for i in range(len(teacher_labels)):
            gt_boxes[int(teacher_labels[i, 0].data)] += [teacher_labels[i, 2:].clone().detach().unsqueeze(0)]

        max_num = 0
        for i in range(batch_size):
            max_num = max(max_num, len(gt_boxes[i]))
            if len(gt_boxes[i]) == 0:
                gt_boxes[i] = torch.zeros((1, 4), device=device)
            else:
                gt_boxes[i] = torch.cat(gt_boxes[i], 0)

        for i in range(batch_size):
            if max_num - gt_boxes[i].size(0):
                gt_boxes[i] = torch.cat((gt_boxes[i], torch.zeros((max_num - gt_boxes[i].size(0), 4), device=device)),
                                        0)
            gt_boxes[i] = gt_boxes[i].unsqueeze(0)

        gt_boxes = torch.cat(gt_boxes, 0)
        gt_boxes *= out_size

        center_anchors = make_center_anchors(anchors_wh=self.imitation_mask_anchors, grid_size=out_size, device=device)
        anchors = center_to_corner(center_anchors).view(-1, 4)  # (N, 4)

        gt_boxes = center_to_corner(gt_boxes)

        mask_batch = torch.zeros([batch_size, out_size, out_size], device=device)

        for i in range(batch_size):
            num_obj = gt_boxes[i].size(0)

            if not num_obj:
                continue

            iou_map = find_jaccard_overlap(anchors, gt_boxes[i], 0).view(out_size, out_size,
                                                                         len(self.imitation_mask_anchors), num_obj)
            max_iou, _ = iou_map.view(-1, num_obj).max(dim=0)
            mask_img = torch.zeros([out_size, out_size], dtype=torch.int64, requires_grad=False).type_as(teacher_features)
            threshold = torch.mul(max_iou, iou_factor)

            for k in range(num_obj):
                mask_per_gt = torch.sum(iou_map[:, :, :, k] > threshold[k], dim=2)
                mask_img += mask_per_gt
                mask_img += mask_img
            mask_batch[i] = mask_img

        mask_batch = mask_batch.clamp(0, 1)
        return mask_batch  # (B, h, w)
