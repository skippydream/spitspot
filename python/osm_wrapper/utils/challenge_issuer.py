# coding=utf-8
"""
OWASP would probably SWAT me if they found this code.
This PoW "CAPTCHA" challenge issuer is NOT CRYPTOGRAPHICALLY SAFE.
It randomly finds (or, I hope it does) a class 3 Cellular Automaton.
https://demonstrations.wolfram.com/ClassifyingTheComplexityAndInformationOfCellularAutomata/

The idea behind it is asking the client to solve this challenge:

Given a 1 Dimensional CA, the server will provide:
- The initial state.
- Part of the automaton key.
- The state after a "small" amount of iterations.

It asks the client to:
- Iterate all possible keyspaces in order to find the expected state at "small"-th iteration.
- After finding the correct key, iterate up to a "big" number of iterations, as a proof of having found the correct CA.

This "CAPTCHA" might be extremely subsceptible to all sort of cryptoanalysis attacks.
For toy projects and non-critical applications it's totally fine and any reasearch the scientific benefits would
outweight any "damage" done, as long as this keeps being used for NON-CRITICAL APPLICATIONS.
"""
import numpy as np
from math import e
import redis
from .namespaced_redis import get_redis_connection

class CellularAutomaton:
    _hash = {}
    size = 0
    def __init__(self, size, key):
        self.size = size
        self.key = key
        items = self.combinations()
        for i in range(items):
            self._hash[np.binary_repr(i, self.size)] = self.key[i]
    def combinations(self):
        return 2**self.size
    def get_key(self):
        return self.key
    def iterate(self, seq):
        original_len = len(seq)
        s = self.size // 2
        res = []
        end = seq[-s:]
        start = seq[:s]
        seq = np.append(end, seq)
        seq = np.append(seq, start)
        for i in range(original_len):
            portion = seq[i:i+self.size]
            res.append(self._hash["".join(map(lambda t: str(t), portion))])
        return np.array(res)


def entropy(labels, base=None):
    value, counts = np.unique(labels, return_counts=True)
    norm_counts = counts / counts.sum()
    base = e if base is None else base
    return -(norm_counts * np.log(norm_counts) / np.log(base)).sum()

"""
    :param key_size             Width of the automaton. 
                                Keep it an odd number and remember that the keyspace grows exponentially (2^2^key_size).
                                An elementary CA has a key_size = 3.
                                
    :param state_size           Width of the space the automaton works on.
                                This allows tuning of collision rates without touching key_size.
                                
    :param simplicity_factor    Space the client is expected to "fill out" with its work.
                                Adding 1 to this value means halving the amout of possible keys.
                                
    :param small_iters          Amount of iterations needed to generate the proof state.
    
    :param big_iters            Amount of iterations needed to generate the challenge state.
"""
def create_challenge(key_size, state_size, simplicity_factor, small_iters, big_iters):
    # @todo correctly seed the state - current implementation is deterministic
    rng = np.random.RandomState(123)
    ent = 0
    initial_state = np.zeros(2 ** state_size)
    initial_state.dtype = 'int64'
    initial_state[1] = 1
    while ent < 0.69:
        # Generate a random automaton with given key size.
        automaton = CellularAutomaton(key_size, rng.randint(0, 2, 2**key_size))
        current = initial_state
        acc = []
        # some iterations to collect states and calculate Shannon entropy
        for i in range(1000):
            current = automaton.iterate(current)
            acc.append(current)
        ent = entropy(acc)
    # The automaton "probably" exhibits class-3 behavior
    current = initial_state
    # Generate the proof state, it will be given as a hint to the client
    for i in range(small_iters):
        # noinspection PyUnboundLocalVariable
        current = automaton.iterate(current)
    proof = current
    # Iterate to the state intended as "solved"
    for i in range(big_iters - small_iters):
        current = automaton.iterate(current)
    challenge = current
    automaton_key = automaton.get_key()
    key_step = 2**simplicity_factor
    original = np.array(automaton_key)
    original[::key_step] = 0
    # That's a little bit of magic, I'm prepending four 1's to the result
    # in order to strip them later and preserve leading zeroes
    hex_string = hex(int('1111%s' % ''.join(challenge.astype(str)), 2))[2:]
    r = get_redis_connection()
    # @todo issue an adequate challenge id. Maybe some client-identifying id.
    challenge_id = 7
    # Challenge expires in 5 minutes in order not to clog redis
    r.set("challenge_%d" % challenge_id, hex_string[1:], ex=300)
    return ({
        "key_size": key_size,
        "state_size": state_size,
        "simplicity_factor": simplicity_factor,
        "small_iters": small_iters,
        "big_iters": big_iters,
        "proof": proof.tolist(),
        "original": original.tolist(),
        "challenge_id": challenge_id,
    })