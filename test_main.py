"""Tests for main.py.

Geometry/topology helpers are tested directly. The draw_* functions are tested
through fake turtle objects so no GUI window is needed.
"""

import math
import unittest
import unittest.mock as mock

import main


class CirclePositionsTests(unittest.TestCase):
    def test_all_nodes_placed_on_circle(self):
        for n in (3, 5, 12):
            positions = main.circle_positions(n)
            self.assertEqual(len(positions), n)
            for x, y in positions:
                self.assertAlmostEqual(math.hypot(x, y), main.NODE_DISTANCE)

    def test_first_node_on_positive_x_axis(self):
        self.assertEqual(main.circle_positions(4)[0], (main.NODE_DISTANCE, 0))


class GridPositionsTests(unittest.TestCase):
    def test_all_nodes_placed(self):
        # Regression: the old code drew rows*cols nodes, silently dropping the
        # remainder (e.g. 9 of 10 nodes, 6 of 7 nodes).
        for n in (3, 5, 7, 9, 10, 12, 16, 20):
            self.assertEqual(len(main.grid_positions(n)), n)

    def test_positions_unique(self):
        for n in (7, 10):
            positions = main.grid_positions(n)
            self.assertEqual(len(set(positions)), len(positions))

    def test_adjacent_same_row_nodes_are_one_step_apart(self):
        distance = main.NODE_DISTANCE
        for n in (7, 10):
            positions = main.grid_positions(n)
            for i in range(n - 1):
                (x1, y1), (x2, y2) = positions[i], positions[i + 1]
                if y1 == y2:  # same row
                    self.assertAlmostEqual(abs(x2 - x1), distance)


class GridEdgesTests(unittest.TestCase):
    def test_every_edge_connects_true_neighbors(self):
        # Regression: the old abs(i-j) check also linked nodes diagonally
        # across row boundaries (e.g. grid index 2 to 3 in a 3-column grid).
        for n in (3, 5, 7, 9, 10, 12, 16):
            positions = main.grid_positions(n)
            edges = main.grid_edges(n)
            self.assertTrue(edges)
            for i, j in edges:
                (x1, y1), (x2, y2) = positions[i], positions[j]
                manhattan = abs(x1 - x2) + abs(y1 - y2)
                self.assertAlmostEqual(
                    manhattan, main.NODE_DISTANCE,
                    msg=f"edge ({i}, {j}) is not between adjacent grid cells for n={n}")

    def test_no_duplicate_edges(self):
        for n in (7, 9, 10):
            edges = main.grid_edges(n)
            normalized = {tuple(sorted(e)) for e in edges}
            self.assertEqual(len(normalized), len(edges))

    def test_known_counts(self):
        # 3x3 grid: 6 horizontal + 6 vertical edges.
        self.assertEqual(len(main.grid_edges(9)), 12)
        # 10 nodes in 3x4 grid: 7 horizontal + 6 vertical edges.
        self.assertEqual(len(main.grid_edges(10)), 13)


class EdgeEndpointsTests(unittest.TestCase):
    def test_horizontal_edge_trimmed_at_both_borders(self):
        start, end = main.edge_endpoints((0, 0), (100, 0))
        self.assertAlmostEqual(start[0], main.NODE_RADIUS)
        self.assertAlmostEqual(start[1], 0)
        self.assertAlmostEqual(end[0], 100 - main.NODE_RADIUS)
        self.assertAlmostEqual(end[1], 0)

    def test_diagonal_edge_stays_on_center_line(self):
        # Regression: the old code shifted both endpoints down by the node
        # radius no matter the edge direction, so diagonal edges (star/ring
        # layouts) did not connect the nodes they were drawn between.
        start, end = main.edge_endpoints((0, 0), (60, 80))
        self.assertAlmostEqual(math.hypot(start[0], start[1]), main.NODE_RADIUS)
        self.assertAlmostEqual(math.hypot(end[0] - 60, end[1] - 80), main.NODE_RADIUS)
        # Start and end lie on the line through both node centers.
        self.assertAlmostEqual(start[0] / start[1], 60 / 80)
        self.assertAlmostEqual((end[0] - 60) / (end[1] - 80), 60 / 80)


# Fakes that record drawing calls instead of opening a GUI window.
class FakeScreen(object):
    def setup(self, **kwargs):
        pass

    def bgcolor(self, color):
        pass


class FakeTurtle(object):
    def __init__(self):
        self.pen_down = False
        self.pos = (0.0, 0.0)
        self.circles = 0
        self.lines = []
        self.writes = []
        self.fillcolors = []

    def penup(self):
        self.pen_down = False

    def pendown(self):
        self.pen_down = True

    def goto(self, x, y):
        if self.pen_down:
            self.lines.append((self.pos, (x, y)))
        self.pos = (x, y)

    def speed(self, value):
        pass

    def color(self, *args):
        pass

    def fillcolor(self, color):
        self.fillcolors.append(color)

    def begin_fill(self):
        pass

    def end_fill(self):
        pass

    def circle(self, radius):
        self.circles += 1

    def write(self, text, **kwargs):
        self.writes.append(text)

    def hideturtle(self):
        pass


class DrawFunctionTests(unittest.TestCase):
    def run_draw_function(self, draw_function, num_nodes):
        turtles = []

        def make_turtle():
            t = FakeTurtle()
            turtles.append(t)
            return t

        with mock.patch.object(main.turtle, "Turtle", make_turtle), \
                mock.patch.object(main.turtle, "Screen", lambda: FakeScreen()), \
                mock.patch.object(main.turtle, "done", lambda: None):
            draw_function(num_nodes)
        return turtles

    def test_rstp_draws_ring(self):
        t, text_turtle = self.run_draw_function(
            main.draw_rstp_spanning_tree_with_animation, 6)
        self.assertEqual(t.circles, 6)
        self.assertEqual(len(t.lines), 6)  # 5 chain edges + 1 closing edge
        self.assertIn("RSTP Spanning Tree", text_turtle.writes)

    def test_mstp_draws_star(self):
        t, text_turtle = self.run_draw_function(
            main.draw_mstp_spanning_tree_with_animation, 6)
        self.assertEqual(t.circles, 6)
        self.assertEqual(len(t.lines), 5)  # every node connected to node 0
        self.assertIn("MSTP Spanning Tree", text_turtle.writes)

    def test_pvstp_draws_star_with_own_title(self):
        # Regression: PVSTP used to be a verbatim copy of MSTP.
        t, text_turtle = self.run_draw_function(
            main.draw_pvstp_spanning_tree_with_animation, 6)
        self.assertEqual(t.circles, 6)
        self.assertEqual(len(t.lines), 5)
        self.assertIn("PVSTP Spanning Tree", text_turtle.writes)
        self.assertNotIn("MSTP Spanning Tree", text_turtle.writes)

    def test_spb_draws_all_nodes(self):
        # Regression: with 10 nodes the old grid code drew only 9.
        t, _ = self.run_draw_function(
            main.draw_spb_spanning_tree_with_animation, 10)
        self.assertEqual(t.circles, 10)
        self.assertEqual(len(t.lines), len(main.grid_edges(10)))

    def test_nodes_filled_with_node_color(self):
        # Regression: NODE_COLOR was defined but never used; nodes came out
        # black because t.color(EDGE_COLOR) also sets the fill color.
        t, _ = self.run_draw_function(
            main.draw_mstp_spanning_tree_with_animation, 4)
        self.assertEqual(t.fillcolors, [main.NODE_COLOR] * 4)

    def _assert_is_a_node_center(self, point, centers):
        self.assertTrue(any(
            math.isclose(point[0], cx, abs_tol=1e-6) and
            math.isclose(point[1], cy, abs_tol=1e-6)
            for cx, cy in centers))

    def test_edges_connect_node_borders(self):
        # Each drawn segment, extended by the node radius along its own
        # direction, must land exactly on the two node centers it joins.
        num_nodes = 4
        t, _ = self.run_draw_function(
            main.draw_rstp_spanning_tree_with_animation, num_nodes)
        centers = main.circle_positions(num_nodes)
        for (x1, y1), (x2, y2) in t.lines:
            dx, dy = x2 - x1, y2 - y1
            length = math.hypot(dx, dy)
            ux, uy = dx / length, dy / length
            extended_start = (x1 - ux * main.NODE_RADIUS, y1 - uy * main.NODE_RADIUS)
            extended_end = (x2 + ux * main.NODE_RADIUS, y2 + uy * main.NODE_RADIUS)
            self._assert_is_a_node_center(extended_start, centers)
            self._assert_is_a_node_center(extended_end, centers)


class InputHandlingTests(unittest.TestCase):
    def test_read_int_rejects_non_numeric_and_too_small(self):
        with mock.patch("builtins.input", side_effect=["abc", "2", "7"]):
            self.assertEqual(main._read_int("n: ", minimum=3), 7)

    def test_main_reprompts_on_invalid_choice(self):
        # Regression: the old invalid-choice message said "enter 1 or 2"
        # although the menu has four options; invalid input also aborted.
        with mock.patch("builtins.input", side_effect=["9", "2", "4"]), \
                mock.patch.object(main, "draw_mstp_spanning_tree_with_animation") as draw:
            main.main()
        draw.assert_called_once_with(4)


if __name__ == "__main__":
    unittest.main()
