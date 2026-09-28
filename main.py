import math
import turtle


# Constants
NODE_RADIUS = 10  # Radius of the nodes
NODE_DISTANCE = 150  # Distance between nodes
EDGE_COLOR = "black"
NODE_COLOR = "blue"
TEXT_COLOR = "black"
DRAW_SPEED = 3  # Speed of the drawing animation
MIN_NODES = 3  # Smallest topology worth drawing


# Layout helpers (pure geometry/topology, testable without a GUI)
def circle_positions(num_nodes, distance=NODE_DISTANCE):
    """Positions of nodes evenly spaced on a circle centered at the origin."""
    return [
        (distance * math.cos(2 * math.pi * i / num_nodes),
         distance * math.sin(2 * math.pi * i / num_nodes))
        for i in range(num_nodes)
    ]


def ring_edges(num_nodes):
    """Edges of a ring topology: consecutive nodes plus a closing edge."""
    return [(i - 1, i) for i in range(1, num_nodes)] + [(num_nodes - 1, 0)]


def star_edges(num_nodes):
    """Edges of a star topology: every node connected to node 0."""
    return [(0, i) for i in range(1, num_nodes)]


def grid_dimensions(num_nodes):
    """Grid size that fits num_nodes in a shape as square as possible."""
    rows = max(int(math.sqrt(num_nodes)), 1)
    cols = math.ceil(num_nodes / rows)
    return rows, cols


def grid_positions(num_nodes, distance=NODE_DISTANCE):
    """Positions of all num_nodes in a centered row-major grid."""
    rows, cols = grid_dimensions(num_nodes)
    positions = []
    for i in range(num_nodes):
        row, col = divmod(i, cols)
        x = (col - (cols - 1) / 2) * distance
        y = ((rows - 1) / 2 - row) * distance
        positions.append((x, y))
    return positions


def grid_edges(num_nodes):
    """Edges between horizontally and vertically adjacent grid nodes."""
    _, cols = grid_dimensions(num_nodes)
    edges = []
    for i in range(num_nodes):
        if i % cols < cols - 1 and i + 1 < num_nodes:
            edges.append((i, i + 1))
        if i + cols < num_nodes:
            edges.append((i, i + cols))
    return edges


def edge_endpoints(p1, p2, radius=NODE_RADIUS):
    """Trim the segment p1-p2 so it starts and ends on the node borders."""
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    length = math.hypot(dx, dy)
    ux, uy = dx / length, dy / length
    start = (p1[0] + ux * radius, p1[1] + uy * radius)
    end = (p2[0] - ux * radius, p2[1] - uy * radius)
    return start, end


# Drawing primitives
def draw_node(t, x, y, label):
    t.penup()
    t.goto(x, y - NODE_RADIUS)
    t.pendown()
    t.fillcolor(NODE_COLOR)
    t.begin_fill()
    t.circle(NODE_RADIUS)
    t.end_fill()
    t.penup()
    t.goto(x, y - NODE_RADIUS - 20)
    t.write(label, align="center", font=("Arial", 10, "normal"))


def draw_edge_with_animation(t, p1, p2):
    start, end = edge_endpoints(p1, p2)
    t.penup()
    t.goto(*start)
    t.pendown()
    t.speed(DRAW_SPEED)  # Set the speed for animation
    t.goto(*end)


def draw_topology(positions, edges, title, description):
    """Draw the nodes and edges, add the title/description, keep the window open."""
    screen = turtle.Screen()
    screen.setup(width=1.0, height=1.0)  # Fullscreen
    screen.bgcolor("white")

    t = turtle.Turtle()
    t.speed(0)  # Set the drawing speed to the maximum
    t.color(EDGE_COLOR)

    for i, (x, y) in enumerate(positions):
        draw_node(t, x, y, str(i))

    for i, j in edges:
        draw_edge_with_animation(t, positions[i], positions[j])

    # Add text to explain what's going on
    text_turtle = turtle.Turtle()
    text_turtle.penup()
    text_turtle.color(TEXT_COLOR)
    text_turtle.goto(0, 250)
    text_turtle.write(title, align="center", font=("Arial", 16, "bold"))
    text_turtle.goto(0, 200)
    text_turtle.write(description, align="center", font=("Arial", 12, "normal"))

    # Hide turtles
    t.hideturtle()
    text_turtle.hideturtle()

    # Keep the window open
    turtle.done()


# One function per STP algorithm; they only differ in layout, edges and text
def draw_rstp_spanning_tree_with_animation(num_nodes):
    draw_topology(
        circle_positions(num_nodes),
        ring_edges(num_nodes),
        "RSTP Spanning Tree",
        "Enhances STP by reducing convergence times through the elimination of listening and learning states and the introduction of port roles and types.",
    )


def draw_star_topology(num_nodes, title, description):
    draw_topology(circle_positions(num_nodes), star_edges(num_nodes), title, description)


def draw_mstp_spanning_tree_with_animation(num_nodes):
    draw_star_topology(
        num_nodes,
        "MSTP Spanning Tree",
        "Extends RSTP to support multiple VLANs, optimizing network resource utilization by creating multiple spanning trees.",
    )


def draw_pvstp_spanning_tree_with_animation(num_nodes):
    draw_star_topology(
        num_nodes,
        "PVSTP Spanning Tree",
        "Cisco's proprietary extension of STP, creating separate spanning tree instances for each VLAN to provide redundancy and load balancing.",
    )


def draw_spb_spanning_tree_with_animation(num_nodes):
    draw_topology(
        grid_positions(num_nodes),
        grid_edges(num_nodes),
        "SPB Spanning Tree",
        "IEEE 802.1aq enables the creation of multiple equal-cost spanning trees, enhancing scalability and convergence in large networks.",
    )


# Main function
def _read_int(prompt, minimum):
    """Keep prompting until the user enters an integer >= minimum."""
    while True:
        raw = input(prompt).strip()
        try:
            value = int(raw)
        except ValueError:
            value = None
        if value is not None and value >= minimum:
            return value
        print(f"Invalid number. Please enter an integer >= {minimum}.")


def main():
    # Prompt the user to choose the STP algorithm
    print("Choose an STP algorithm:")
    print("1. Rapid Spanning Tree Protocol (RSTP)")
    print("2. Multiple Spanning Tree Protocol (MSTP)")
    print("3. Per-VLAN Spanning Tree Protocol (PVSTP)")
    print("4. IEEE 802.1aq - Shortest Path Bridging (SPB)")

    draw_functions = {
        "1": draw_rstp_spanning_tree_with_animation,
        "2": draw_mstp_spanning_tree_with_animation,
        "3": draw_pvstp_spanning_tree_with_animation,
        "4": draw_spb_spanning_tree_with_animation,
    }

    choice = input("Enter your choice (1, 2, 3, or 4): ")
    while choice not in draw_functions:
        print("Invalid choice. Please enter 1, 2, 3, or 4.")
        choice = input("Enter your choice (1, 2, 3, or 4): ")

    num_nodes = _read_int("Enter the number of nodes: ", minimum=MIN_NODES)

    draw_functions[choice](num_nodes)


if __name__ == "__main__":
    main()
