import tensorflow as tf
import numpy as np
from baselines.a2c.utils import fc
from tensorflow.python.ops import math_ops

class Pd(object):
    """
    A particular probability distribution
    """
    def flatparam(self):
        raise NotImplementedError
    def mode(self):
        raise NotImplementedError
    def neglogp(self, x):
        # Usually it's easier to define the negative logprob
        raise NotImplementedError
    def kl(self, other):
        raise NotImplementedError
    def entropy(self):
        raise NotImplementedError
    def sample(self):
        raise NotImplementedError
    def logp(self, x):
        return - self.neglogp(x)
    def get_shape(self):
        return self.flatparam().shape
    @property
    def shape(self):
        return self.get_shape()
    def __getitem__(self, idx):
        return self.__class__(self.flatparam()[idx])

class PdType(tf.Module):
    """
    Parametrized family of probability distributions
    """
    def pdclass(self):
        raise NotImplementedError
    def pdfromflat(self, flat):
        return self.pdclass()(flat)
    def pdfromlatent(self, latent_vector):
        raise NotImplementedError
    def param_shape(self):
        raise NotImplementedError
    def sample_shape(self):
        raise NotImplementedError
    def sample_dtype(self):
        raise NotImplementedError

    def __eq__(self, other):
        return (type(self) == type(other)) and (self.__dict__ == other.__dict__)

class CategoricalPdType(PdType):
    def __init__(self, latent_shape, ncat, init_scale=1.0, init_bias=0.0):
        self.ncat = ncat
        self.matching_fc = _matching_fc(latent_shape, 'pi', self.ncat, init_scale=init_scale, init_bias=init_bias)

    def pdclass(self):
        return CategoricalPd
    def pdfromlatent(self, latent_vector):
        pdparam = self.matching_fc(latent_vector)
        return self.pdfromflat(pdparam), pdparam

    def param_shape(self):
        return [self.ncat]
    def sample_shape(self):
        return []
    def sample_dtype(self):
        return tf.int32


class CategoricalPd(Pd):
    def __init__(self, logits):
        self.logits = logits
    def flatparam(self):
        return self.logits
    def mode(self):
        return tf.argmax(self.logits, axis=-1)

    @property
    def mean(self):
        return tf.nn.softmax(self.logits)

    def neglogp(self, x):
        # return tf.nn.sparse_softmax_cross_entropy_with_logits(logits=self.logits, labels=x)
        # Note: we can't use sparse_softmax_cross_entropy_with_logits because
        #       the implementation does not allow second-order derivatives...
        if x.dtype in {tf.uint8, tf.int32, tf.int64}:
            # one-hot encoding
            x_shape_list = x.shape.as_list()
            logits_shape_list = self.logits.get_shape().as_list()[:-1]
            for xs, ls in zip(x_shape_list, logits_shape_list):
                if xs is not None and ls is not None:
                    assert xs == ls, 'shape mismatch: {} in x vs {} in logits'.format(xs, ls)

            x = tf.one_hot(x, self.logits.get_shape().as_list()[-1])
        else:
            # already encoded
            print('logits is {}'.format(self.logits))
            assert x.shape.as_list() == self.logits.shape.as_list()

        return tf.nn.softmax_cross_entropy_with_logits(logits=self.logits, labels=x)

    def kl(self, other):
        a0 = self.logits - tf.reduce_max(self.logits, axis=-1, keepdims=True)
        a1 = other.logits - tf.reduce_max(other.logits, axis=-1, keepdims=True)
        ea0 = tf.exp(a0)
        ea1 = tf.exp(a1)
        z0 = tf.reduce_sum(ea0, axis=-1, keepdims=True)
        z1 = tf.reduce_sum(ea1, axis=-1, keepdims=True)
        p0 = ea0 / z0
        return tf.reduce_sum(p0 * (a0 - tf.math.log(z0) - a1 + tf.math.log(z1)), axis=-1)
    def entropy(self):
        a0 = self.logits - tf.reduce_max(self.logits, axis=-1, keepdims=True)
        ea0 = tf.exp(a0)
        z0 = tf.reduce_sum(ea0, axis=-1, keepdims=True)
        p0 = ea0 / z0
        return tf.reduce_sum(p0 * (tf.math.log(z0) - a0), axis=-1)
    def sample(self):
        u = tf.random.uniform(tf.shape(self.logits), dtype=self.logits.dtype, seed=0)
        return tf.argmax(self.logits - tf.math.log(-tf.math.log(u)), axis=-1)
    @classmethod
    def fromflat(cls, flat):
        return cls(flat)

def make_pdtype(latent_shape, ac_space, init_scale=1.0):
    from gym import spaces
    if isinstance(ac_space, spaces.Discrete):
        return CategoricalPdType(latent_shape, ac_space.n, init_scale)
    else:
        raise NotImplementedError

def _matching_fc(tensor_shape, name, size, init_scale, init_bias):
    if tensor_shape[-1] == size:
        return lambda x: x
    else:
        return fc(tensor_shape, name, size, init_scale=init_scale, init_bias=init_bias)
