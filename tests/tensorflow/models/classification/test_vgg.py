import pytest

from typing import Union, Callable
import numpy

from neuralmagicML.tensorflow.utils import tf_compat
from neuralmagicML.tensorflow.models import (
    ModelRegistry,
    vgg11,
    vgg11bn,
    vgg13,
    vgg13bn,
    vgg16,
    vgg16bn,
    vgg19,
    vgg19bn,
)


@pytest.mark.parametrize(
    "key,pretrained,test_input,const",
    [
        ("vgg11", False, True, vgg11),
        ("vgg11", True, False, vgg11),
        ("vgg11bn", False, True, vgg11bn),
        ("vgg11bn", True, False, vgg11bn),
        ("vgg13", False, True, vgg13),
        ("vgg13", True, False, vgg13),
        ("vgg13bn", False, True, vgg13bn),
        ("vgg13bn", True, False, vgg13bn),
        ("vgg16", False, True, vgg16),
        ("vgg16", True, False, vgg16),
        ("vgg16", "base", False, vgg16),
        ("vgg16", "recal", False, vgg16),
        ("vgg16", "recal-perf", False, vgg16),
        ("vgg16bn", False, True, vgg16bn),
        ("vgg16bn", True, False, vgg16bn),
        ("vgg19", False, True, vgg19),
        ("vgg19", True, False, vgg19),
        ("vgg19bn", False, True, vgg19bn),
        ("vgg19bn", True, False, vgg19bn),
    ],
)
def test_vggs(
    key: str, pretrained: Union[bool, str], test_input: bool, const: Callable
):
    # test out the stand alone constructor
    with tf_compat.Graph().as_default() as graph:
        inputs = tf_compat.placeholder(
            tf_compat.float32, [None, 224, 224, 3], name="inputs"
        )
        logits = const(inputs, training=False)

        if test_input:
            with tf_compat.Session() as sess:
                sess.run(tf_compat.global_variables_initializer())
                out = sess.run(
                    logits, feed_dict={inputs: numpy.random.random((1, 224, 224, 3))}
                )
                assert out.sum() != 0

    # test out the registry
    with tf_compat.Graph().as_default() as graph:
        inputs = tf_compat.placeholder(
            tf_compat.float32, [None, 224, 224, 3], name="inputs"
        )
        logits = ModelRegistry.create(key, inputs, training=False)

        with tf_compat.Session() as sess:
            if test_input:
                sess.run(tf_compat.global_variables_initializer())
                out = sess.run(
                    logits, feed_dict={inputs: numpy.random.random((1, 224, 224, 3))}
                )
                assert out.sum() != 0

            if pretrained:
                ModelRegistry.load_pretrained(key, pretrained)

                if test_input:
                    out = sess.run(
                        logits,
                        feed_dict={inputs: numpy.random.random((1, 224, 224, 3))},
                    )
                    assert out.sum() != 0
