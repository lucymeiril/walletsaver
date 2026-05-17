from fastapi import APIRouter, HTTPException

from services.snapshot_repo import SnapshotRepo, get_conn

router = APIRouter()


def _build_tree(nodes) -> list[dict]:
    node_map = {}
    for n in nodes:
        node_map[n.id] = {
            "id": n.id,
            "name_kr": n.name_kr,
            "name_slug": n.name_slug,
            "level": n.level,
            "path": n.path,
            "parent_id": n.parent_id,
            "children": [],
        }

    roots = []
    for n in nodes:
        node = node_map[n.id]
        if n.parent_id and n.parent_id in node_map:
            node_map[n.parent_id]["children"].append(node)
        else:
            roots.append(node)

    return roots


@router.get("/categories")
def get_categories():
    try:
        conn = get_conn()
        repo = SnapshotRepo(conn)
        nodes = repo.all_categories()
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))

    tree = _build_tree(nodes)
    return {"categories": tree, "total_nodes": len(nodes)}
