# ``CompiledGraph`` lived in ``langgraph.graph.state`` in langgraph 0.2.x and
# was renamed/moved in 0.3+. Best-effort import that works on both vintages,
# falling back to ``Any`` so this module can be imported without crashing the
# entire backend just because of a type hint.
try:
    from langgraph.graph.state import CompiledGraph  # type: ignore
except ImportError:  # langgraph >= 0.3
    try:
        from langgraph.graph.state import CompiledStateGraph as CompiledGraph  # type: ignore
    except ImportError:
        from typing import Any as CompiledGraph  # type: ignore

from langchain_core.runnables.graph import MermaidDrawMethod


def save_graph_as_png(app: "CompiledGraph", output_file_path) -> None:
    png_image = app.get_graph().draw_mermaid_png(draw_method=MermaidDrawMethod.API)
    file_path = output_file_path if len(output_file_path) > 0 else "graph.png"
    with open(file_path, "wb") as f:
        f.write(png_image)