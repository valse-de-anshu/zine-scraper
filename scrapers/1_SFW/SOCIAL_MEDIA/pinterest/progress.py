from rich.tree import Tree
from core.ui import align_header

def render_progress_tree(state: dict) -> Tree:
    """Construct and return the visual Tree for Live status updates."""
    tree = Tree(
        f"[title]◆ {state['board_title']} ({state['board_idx']}/{state['total_boards']})[/title]"
    )
    tree.add(align_header("❖ Location", f"[info]{state['location']}[/info]"))

    if state["status"] == "extracting":
        import time
        blink_state = int(time.time() * 3) % 2
        ball_style = "info" if blink_state == 0 else "unselected"
        tree.add(f"[{ball_style}]●[/{ball_style}] Scrolling and targeting all images for download...")
        return tree

    tree.add(align_header("Total Pins", f"[info]{state['pins_total']}[/info]"))

    download_stats = f"[success]{state['pins_existing']} existing[/success]"
    if state["pins_downloaded"] > 0:
        download_stats += f", [info]{state['pins_downloaded']} new[/info]"

    if state["status"] == "finished":
        tree.add(align_header("Status",   "[success]Complete[/success]"))
        tree.add(align_header("Progress", download_stats))
        return tree

    tree.add(align_header("Progress", download_stats))

    if state["status"] == "downloading" and state["current_pin"]:
        pin_branch = tree.add(f"[menu]⬢ {state['current_pin']}[/menu]")
        prog = state["progress"]
        if prog and not prog.get("done"):
            import time
            blink_state = int(time.time() * 3) % 2
            ball_style = "warning" if blink_state == 0 else "unselected"
            pin_branch.add(f"[{ball_style}]●[/{ball_style}] Downloading...")
        elif prog and prog.get("done"):
            color = "success" if prog.get("success") else "error"
            text  = "Complete" if prog.get("success") else "Failed"
            pin_branch.add(f"[{color}]● {text}[/{color}]")

    return tree
