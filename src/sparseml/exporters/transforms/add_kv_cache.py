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

from typing import Any, Dict, List

import numpy as np
import onnx.helper
from onnx import ModelProto, NodeProto

from sparseml.exporters.transforms import OnnxTransform
from sparseml.exporters.transforms.utils import get_structural_matches
from sparseml.onnx.utils import ONNXGraph


__all__ = ["AddKeyValueCache"]


GATHER_MATCHING_RULE_KEY = dict(
    op_type="Gather",
    parent_ops=[["Shape"]],
    children_ops=[["Add", "Cast", "Range"]],

)

class AddKeyValueCache(OnnxTransform):
    """
    """

    def transform(self, model: ModelProto) -> ModelProto:
        graph = ONNXGraph(model)

        gather_nodes = get_structural_matches(graph, **GATHER_MATCHING_RULE_KEY)
        gather_nodes = [match for match in gather_nodes if match.node.name.endswith('15')]
        assert len(gather_nodes) == 20

        new_input_to_add = f"cache_length"
        cache_length = onnx.helper.make_tensor_value_info(
            name=f"cache_length",
            elem_type=onnx.TensorProto.INT64,
            shape=(),

        )
        model.graph.input.insert(-1, cache_length)

        for match_idx, match in enumerate(gather_nodes):
            add_node = match.children[0][0]
            add_node.input[1] = new_input_to_add

        return model







    #     for i, (slice_nodes, add_nodes) in enumerate(
    #         zip(nodes_connect_to_slice, nodes_connect_to_add)
    #     ):
    #         input_name = f"past_key_values.{i}.key"
    #
    #         # first, make Shape node
    #         shape_node = onnx.helper.make_node(
    #             op_type="Shape",
    #             inputs=[input_name],
    #             outputs=[f"past_key_values.{i}.key_shape"],
    #             name=f"past_key_values.{i}.key_shape",
    #         )
    #
    #         # second, make Gather node
    #         indices = onnx.helper.make_tensor(
    #             f"indices_{i}", onnx.TensorProto.INT64, (), [2]
    #         )
    #
    #         axes = onnx.helper.make_tensor(
    #             f"axes_{i}", onnx.TensorProto.INT64, [1], [0]
    #         )
    #
    #         model.graph.initializer.append(indices)
    #         model.graph.initializer.append(axes)
    #
    #         gather_node = onnx.helper.make_node(
    #             op_type="Gather",
    #             inputs=[f"past_key_values.{i}.key_shape", f"indices_{i}"],
    #             outputs=[f"past_key_values.{i}.key_gather"],
    #             name=f"past_key_values.{i}.key_gather",
    #             axis=0,
    #         )
    #
    #         self.add_node_deferred(shape_node)
    #         self.add_node_deferred(gather_node)
    #
    #         # add the slice nodes
    #         for k, match in enumerate(slice_nodes):
    #             slice_node = match.node
    #
    #             # now, add the Unsqueze node
    #             unsqueeze_node = onnx.helper.make_node(
    #                 op_type="Unsqueeze",
    #                 inputs=[f"past_key_values.{i}.key_gather", f"axes_{i}"],
    #                 outputs=[f"past_key_values.{i}.{k}.key_unsqueeze"],
    #                 name=f"past_key_values.{i}.{k}.key_unsqueeze",
    #             )
    #
    #             # now replace the slice node
    #             graph.update_node_input(
    #                 node=slice_node,
    #                 input_id=f"past_key_values.{i}.{k}.key_unsqueeze",
    #                 input_idx=1,
    #             )
    #
    #             model.graph.node.insert(
    #                 [
    #                     i
    #                     for i, n in enumerate(graph._model.graph.node)
    #                     if n.name == slice_node.name
    #                 ][0],
    #                 unsqueeze_node,
    #             )
    #
    #         # add the add nodes
    #         for j, match in enumerate(add_nodes):
    #
    #             match_gather_node = match.node
    #             unsqueeze_node = match.children[0][0]
    #
    #             # now, add the Add node
    #             add_node = onnx.helper.make_node(
    #                 op_type="Add",
    #                 inputs=[
    #                     match_gather_node.output[0],
    #                     f"past_key_values.{i}.key_gather",
    #                 ],
    #                 outputs=[f"past_key_values.{i}.{j}.key_add"],
    #                 name=f"past_key_values.{i}.{j}.key_add",
    #             )
    #             unsqueeze_node.input[0] = f"past_key_values.{i}.{j}.key_add"
    #
    #             model.graph.node.insert(
    #                 [
    #                     i
    #                     for i, n in enumerate(graph._model.graph.node)
    #                     if n.name == unsqueeze_node.name
    #                 ][0],
    #                 add_node,
    #             )
    #
    #             self.add_node_deferred(add_node)
    #
    #         model.graph.node.insert(
    #             0,
    #             gather_node,
    #         )
    #
    #         model.graph.node.insert(
    #             0,
    #             shape_node,
    #         )
    #
    #         #add single adds
    #         match = nodes_connect_to_add_gather[i]
    #         new_gather = match.node
    #         new_cast_node = match.children[0][0]
    #         new_add_node = onnx.helper.make_node(
    #             op_type="Add",
    #             inputs=[f"past_key_values.{i}.key_gather", new_gather.output[0]],
    #             outputs=[f"past_key_values.{i}.key_add_gather"],
    #             name=f"past_key_values.{i}.key_add_gather",
    #         )
    #         new_cast_node.input[0] = f"past_key_values.{i}.key_add_gather"
    #
    #         model.graph.node.insert(
    #             [
    #                 i
    #                 for i, n in enumerate(graph._model.graph.node)
    #                 if n.name == new_cast_node.name
    #             ][0],
    #             new_add_node,
    #         )
    #
    #         self.add_node_deferred(new_add_node)
    #
        return model
    #
    # def add_value_cache(
    #     self,
    #     model: ModelProto,
    #     graph: ONNXGraph,
    #     matching_rule: Dict[str, Any] = CODEGEN_MATCHING_RULE_VALUE,
    #     concat_axis: List[str] = CODEGEN_VALUE_CACHE_DIMS.index("past_sequence_len"),
    #     cache_dims: int = CODEGEN_VALUE_CACHE_DIMS,
    # ):
    #     """
    #     Adds a value cache to the model. This means that a Concat node is added,
    #     which concatenates the value of the token that is currently
    #     being processed with the value cache.
    #
    #     :param model: The model to add the value cache to
    #     :param graph: The graph of the model
    #     :param matching_rule: The rule to use to find the MatMul node that performs
    #         the V x Softmax(QK^T) operation
    #     :param concat_axis: The axis to concatenate the cache with values on
    #     :param cache_dims: The dimensions of the cache
    #     """
    #     value_matches = get_structural_matches(graph, **matching_rule)
    #     if not value_matches:
    #         raise ValueError("Could not find matching nodes for the key cache. ")
    #
    #     for match_index, match in enumerate(value_matches):
    #         self.log_match(match)
    #         value_node = match.parents[1][0]
    #         matmul_node = match.node
    #         self.concatenate_cache_with_model_outputs(
    #             matmul_node=matmul_node,
    #             target_node=value_node,
    #             index=match_index,
    #             model=model,
    #             graph=graph,
    #             concat_axis=concat_axis,
    #             cache_dims=cache_dims,
    #             input_to_concat_name=f"past_key_values.{match_index}.value",
    #             output_from_concat_name=f"present.{match_index}.value_",
    #         )
    #
    # def add_key_cache(
    #     self,
    #     model: ModelProto,
    #     graph: ONNXGraph,
    #     matching_rule: Dict[str, Any] = CODEGEN_MATCHING_RULE_KEY,
    #     concat_axis: List[str] = CODEGEN_KEY_CACHE_DIMS.index("past_sequence_len"),
    #     cache_dims: int = CODEGEN_KEY_CACHE_DIMS,
    # ):
    #     """
    #     Adds a key cache to the model. This means that a Concat node is added,
    #     that concatenates the key of the token that is currently
    #     being processed with the key cache.
    #
    #     :param model: The model to add the key cache to
    #     :param graph: The graph of the model
    #     :param matching_rule: The rule to use to find the MatMul node that performs
    #         the Q x K^T operation
    #     :param concat_axis: The axis to concatenate the cache with keys on
    #     :param cache_dims: The dimensions of the cache
    #     """
    #     key_matches = get_structural_matches(graph, **matching_rule)
    #     if not key_matches:
    #         raise ValueError("Could not find matching nodes for the key cache. ")
    #     key_matches = [match for match in key_matches if match.node.name.endswith('Transpose_1')]
    #     for match_index, match in enumerate(key_matches):
    #         transpose_node = match.node
    #         output_from_transpose = transpose_node.output[0]
    #
    #         input_to_concat_name = f"past_key_values.{match_index}.key"
    #         output_from_concat_name = f"present.{match_index}.key_"
    #
    #         input_to_concat = onnx.helper.make_tensor_value_info(
    #             input_to_concat_name,
    #             onnx.TensorProto.FLOAT,
    #             cache_dims,
    #         )
    #
    #         output_from_concat = onnx.helper.make_tensor_value_info(
    #             output_from_concat_name,
    #             onnx.TensorProto.FLOAT,
    #             cache_dims,
    #         )
    #
    #         concat_node = onnx.helper.make_node(
    #             op_type="Concat",
    #             inputs=[input_to_concat_name, output_from_transpose],
    #             outputs=[output_from_concat_name],
    #             axis=-2,
    #             name=f"Concat_Key_{match_index}",
    #         )
    #
    #         match.children[0][0].input[0] = output_from_concat_name
    #         match.children[1][0].input[0] = output_from_concat_name
    #
    #         model.graph.node.insert(
    #             [
    #                 i
    #                 for i, n in enumerate(graph._model.graph.node)
    #                 if n.name == match.children[0][0].name
    #             ][0],
    #             concat_node,
    #         )
    #         model.graph.input.insert(-1, input_to_concat)
    #         model.graph.output.insert(-1, output_from_concat)
    #         self.add_node_deferred(concat_node)
    #
    #
    #
    # def concatenate_cache_with_model_outputs(
    #     self,
    #     matmul_node: NodeProto,
    #     target_node: NodeProto,
    #     index: int,
    #     model: ModelProto,
    #     graph: ONNXGraph,
    #     concat_axis: int,
    #     cache_dims: List[str],
    #     input_to_concat_name: str,
    #     output_from_concat_name: str,
    # ):
    #     """
    #     Insert a Concat node into the model that:
    #      - adds the cache input as an input to the model
    #      - concatenates the output of the target node with the cache input
    #      - adds the concatenation as an output to the model
    #      - replaces the input of the MatMul node with the output of the Concat node
    #
    #     :param matmul_node: The MatMul node to replace the input of
    #     :param target_node: The node whose output should be concatenated with the cache
    #     :param index: The index of the cache
    #     :param model: The model to add the Concat node to
    #     :param graph: The graph of the model
    #     :param concat_axis: The axis to concatenate the cache with values on
    #     :param cache_dims: The dimensions of the cache
    #     :param input_to_concat_name: The name of the input to the Concat node
    #     :param output_from_concat_name: The name of the output from the Concat node
    #     """
    #
    #     input_to_matmul = target_node.output[0]
    #     input_index_matmul = [
    #         i for i, x in enumerate(matmul_node.input) if x == input_to_matmul
    #     ][0]
    #     matmul_node.input[input_index_matmul] = output_from_concat_name
    #
    #     input_to_concat = onnx.helper.make_tensor_value_info(
    #         input_to_concat_name,
    #         onnx.TensorProto.FLOAT,
    #         cache_dims,
    #     )
    #
    #     output_from_concat = onnx.helper.make_tensor_value_info(
    #         output_from_concat_name,
    #         onnx.TensorProto.FLOAT,
    #         cache_dims,
    #     )
    #
    #     is_key = input_to_concat_name.endswith("key")
    #
    #     concat_node = onnx.helper.make_node(
    #         op_type="Concat",
    #         inputs=[input_to_concat_name, input_to_matmul],
    #         outputs=[output_from_concat_name],
    #         axis=concat_axis,
    #         name=f"Concat_Key_{index}" if is_key else f"Concat_Value_{index}",
    #     )
    #
    #     model.graph.node.insert(
    #         [
    #             i
    #             for i, n in enumerate(graph._model.graph.node)
    #             if n.name == matmul_node.name
    #         ][0],
    #         concat_node,
    #     )
    #     model.graph.input.insert(-1, input_to_concat)
    #     model.graph.output.insert(-1, output_from_concat)
    #     self.add_node_deferred(concat_node)
