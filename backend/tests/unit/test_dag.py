import random
import time

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from taskboard.domain import dag


def test_self_dependency_is_cycle():
    assert dag.cycle_if_added([], "a", "a") == ["a", "a"]


def test_direct_cycle_detected_with_path():
    edges = [("b", "a")]  # b depends on a
    assert dag.cycle_if_added(edges, "a", "b") == ["a", "b", "a"]


def test_long_cycle_detected():
    # a <- b <- c <- d  (each depends on previous)
    edges = [("b", "a"), ("c", "b"), ("d", "c")]
    cycle = dag.cycle_if_added(edges, "a", "d")
    assert cycle == ["a", "d", "c", "b", "a"]


def test_diamond_is_not_a_cycle():
    edges = [("b", "a"), ("c", "a"), ("d", "b")]
    assert dag.cycle_if_added(edges, "d", "c") is None


def test_topological_order_dependencies_first_and_deterministic():
    nodes = ["a", "b", "c", "d", "e"]
    edges = [("c", "a"), ("c", "b"), ("d", "c"), ("e", "a")]
    order = dag.topological_order(nodes, edges)
    pos = {n: i for i, n in enumerate(order)}
    for t, d in edges:
        assert pos[d] < pos[t]
    assert order == dag.topological_order(list(reversed(nodes)), edges)
    assert order == ["a", "b", "c", "d", "e"]


def test_topological_order_tie_break_key():
    order = dag.topological_order([1, 2, 3], [], key=lambda n: -n)
    assert order == [3, 2, 1]


def test_topological_order_raises_on_cycle():
    with pytest.raises(dag.CycleError) as exc:
        dag.topological_order(["a", "b", "c"], [("a", "b"), ("b", "c"), ("c", "a")])
    cyc = exc.value.cycle
    assert cyc[0] == cyc[-1] and set(cyc) == {"a", "b", "c"}


def test_edges_to_unknown_nodes_ignored():
    assert dag.topological_order(["a"], [("a", "zzz")]) == ["a"]


def test_blocked_and_ready():
    nodes = ["a", "b", "c", "d"]
    edges = [("b", "a"), ("c", "b"), ("d", "a")]
    blocked, ready = dag.blocked_and_ready(nodes, edges, done=set())
    assert blocked == {"b", "c", "d"} and ready == {"a"}
    blocked, ready = dag.blocked_and_ready(nodes, edges, done={"a"})
    assert blocked == {"c"} and ready == {"b", "d"}
    blocked, ready = dag.blocked_and_ready(nodes, edges, done={"a", "b", "c", "d"})
    assert blocked == set() and ready == set()


@st.composite
def random_dag(draw):
    n = draw(st.integers(min_value=1, max_value=40))
    edges = set()
    for _ in range(draw(st.integers(min_value=0, max_value=120))):
        a = draw(st.integers(0, n - 1))
        b = draw(st.integers(0, n - 1))
        if a > b:  # only edges from higher to lower index => acyclic
            edges.add((a, b))
    return list(range(n)), sorted(edges)


@given(random_dag())
@settings(max_examples=200, deadline=None)
def test_property_topological_order_valid(graph):
    nodes, edges = graph
    order = dag.topological_order(nodes, edges)
    assert sorted(order) == nodes
    pos = {n: i for i, n in enumerate(order)}
    assert all(pos[d] < pos[t] for t, d in edges)


@given(random_dag(), st.data())
@settings(max_examples=200, deadline=None)
def test_property_cycle_check_agrees_with_toposort(graph, data):
    nodes, edges = graph
    a = data.draw(st.sampled_from(nodes))
    b = data.draw(st.sampled_from(nodes))
    predicted = dag.cycle_if_added(edges, a, b)
    try:
        dag.topological_order(nodes, [*edges, (a, b)])
        actual_cycle = a == b
    except dag.CycleError:
        actual_cycle = True
    assert (predicted is not None) == actual_cycle
    if predicted:
        assert predicted[0] == a and predicted[1] == b and predicted[-1] == a
        edge_set = set(edges) | {(a, b)}
        assert all((x, y) in edge_set for x, y in zip(predicted, predicted[1:], strict=False))


@pytest.mark.slow
def test_performance_large_graph():
    rng = random.Random(42)
    n = 10_000
    nodes = list(range(n))
    edges = set()
    while len(edges) < 30_000:
        a, b = rng.randrange(n), rng.randrange(n)
        if a > b:
            edges.add((a, b))
    edges = list(edges)
    t0 = time.perf_counter()
    order = dag.topological_order(nodes, edges)
    blocked, ready = dag.blocked_and_ready(nodes, edges, done=set(range(0, n, 3)))
    cyc = dag.cycle_if_added(edges, 0, n - 1)
    elapsed = time.perf_counter() - t0
    assert len(order) == n
    assert ready and blocked
    assert cyc is None or cyc[0] == 0
    assert elapsed < 2.0, f"too slow: {elapsed:.3f}s"
