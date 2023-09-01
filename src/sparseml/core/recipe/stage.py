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

from typing import Dict, Any, List
from pydantic import BaseModel, Field, root_validator

from sparseml.core.recipe.args import RecipeArgs
from sparseml.core.recipe.modifier import RecipeModifier
from sparseml.core.framework import Framework
from sparseml.core.modifier import StageModifiers


__all__ = ["RecipeStage"]


class RecipeStage(BaseModel):
    group: str = None
    args: RecipeArgs = None
    enabled: bool = True
    modifiers: List[RecipeModifier] = Field(default_factory=list)
    _args_evaluated: RecipeArgs = None

    def evaluate(self, parent_args: RecipeArgs):
        merged_args = self.args.combine(parent_args)
        self._args_evaluated = merged_args.evaluate()
        for modifier in self.modifiers:
            modifier.evaluate(merged_args)

    def create_modifiers(
        self, framework: Framework, parent_args: RecipeArgs = None
    ) -> StageModifiers:
        if parent_args is not None:
            self.evaluate(parent_args)

        stage_modifiers = StageModifiers()
        for index, modifier in enumerate(self.modifiers):
            modifier = modifier.create_modifier(framework)
            modifier.group = self.group
            modifier.index = index

        return stage_modifiers

    @root_validator(pre=True)
    def remap_modifiers(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        modifiers = []
        add_modifiers, remove_keys = RecipeStage._combine_modifiers(values)
        modifiers.extend(add_modifiers)
        for key in remove_keys:
            del values[key]
        values["modifiers"] = modifiers

        return values

    def dict(self, *args, **kwargs) -> Dict[str, Any]:
        dict_ = super().dict(*args, **kwargs)
        modifier_groups = dict()

        for modifier in dict_["modifiers"]:
            group = modifier["group"]
            del modifier["group"]
            if group not in modifier_groups:
                modifier_groups[group] = []
            modifier_groups[group].append(modifier)

        for group, modifiers in modifier_groups.items():
            name = f"{group}_modifiers" if group != "default" else "modifiers"
            dict_[name] = modifiers

        del dict_["modifiers"]

        return dict_

    @staticmethod
    def _combine_modifiers(values: Dict[str, Any]) -> List[Dict[str, Any]]:
        modifiers = []

        for key, value in list(values.items()):
            if key.endswith("_modifiers") or key == "modifiers":
                group = (
                    key.rsplit("_modifiers", 1)[0]
                    if key.endswith("_modifiers")
                    else "default"
                )
                for modifier in value:
                    modifier["group"] = group
                    modifiers.append(modifier)

        return modifiers
