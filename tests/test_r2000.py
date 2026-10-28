# dwgdump on R2000 input (issue 7). LibreDWG's JSON gives an R2000 block header first_entity/last_entity and the
# entities next_entity links (a 2D polyline first_vertex/last_vertex with next_entity links between the vertices),
# not the entities/vertex arrays of R2004 and later. The unit tests build the trees by hand; the end to end test
# writes an R2000 drawing with dwgwrite, so nothing in it comes from a reader.
import json
import os
import unittest

from common import dwg, load_json, run, scratch
import libredwg_json as lj


def href(code, h):
    return [code, 1 if h < 256 else 2, h, h] if h else [code, 0, 0, 0]


def obj(kind, h, **kw):
    o = {"entity": kind, "handle": [0, 1 if h < 256 else 2, h]}
    o.update(kw)
    return o


def tree(objects):
    return {"FILEHEADER": {"version": "AC1015"}, "OBJECTS": objects}


def header(name, first, last):
    return {"object": "BLOCK_HEADER", "handle": [0, 1, 64], "name": name, "first_entity": href(4, first), "last_entity": href(4, last)}


class Chains(unittest.TestCase):
    def test_entities_follow_next_entity_from_first_entity(self):
        objs = [header("*Model_Space", 80, 81),
                obj("LINE", 80, next_entity=href(4, 82)),
                obj("CIRCLE", 82, next_entity=href(4, 81)),
                obj("ARC", 81, next_entity=href(4, 0)),
                obj("LINE", 90)]  # not in the chain
        d = lj.Drawing(tree(objs))
        self.assertEqual([e["entity"] for e in d.entities("*Model_Space")], ["LINE", "CIRCLE", "ARC"])

    def test_the_chain_stops_at_last_entity(self):
        objs = [header("*Model_Space", 80, 82),
                obj("LINE", 80, next_entity=href(4, 82)),
                obj("CIRCLE", 82, next_entity=href(4, 81)),
                obj("ARC", 81, next_entity=href(4, 0))]
        d = lj.Drawing(tree(objs))
        d.blocks["*Model_Space"]["last_entity"] = href(4, 82)
        self.assertEqual([e["entity"] for e in d.entities("*Model_Space")], ["LINE", "CIRCLE"])

    def test_a_loop_does_not_hang(self):
        objs = [header("*Model_Space", 80, 81), obj("LINE", 80, next_entity=href(4, 81)), obj("LINE", 81, next_entity=href(4, 80))]
        self.assertEqual(len(lj.Drawing(tree(objs)).entities("*Model_Space")), 2)

    def test_an_empty_block_has_no_entities(self):
        self.assertEqual(lj.Drawing(tree([header("*Model_Space", 0, 0)])).entities("*Model_Space"), [])

    def test_an_r2004_header_still_uses_its_entities_array(self):
        hdr = {"object": "BLOCK_HEADER", "handle": [0, 1, 64], "name": "*Model_Space", "entities": [href(3, 81), href(3, 80)]}
        d = lj.Drawing(tree([hdr, obj("LINE", 80), obj("ARC", 81)]))
        self.assertEqual([e["entity"] for e in d.entities("*Model_Space")], ["ARC", "LINE"])

    def test_vertices_of_an_r2000_polyline_follow_first_vertex(self):
        pl = obj("POLYLINE_2D", 74, first_vertex=href(4, 75), last_vertex=href(4, 77))
        objs = [pl, obj("VERTEX_2D", 75, point=[0, 0, 0], next_entity=href(4, 76)), obj("VERTEX_2D", 76, point=[1, 0, 0], next_entity=href(4, 77)),
                obj("VERTEX_2D", 77, point=[2, 0, 0], next_entity=href(4, 0)), obj("VERTEX_2D", 99, point=[9, 9, 9])]
        d = lj.Drawing(tree(objs))
        self.assertEqual([v["point"][0] for v in d.vertices_2d(pl)], [0, 1, 2])


class EndToEnd(unittest.TestCase):
    def test_a_line_written_as_r2000_is_read(self):
        with scratch() as tmp:
            src = os.path.join(tmp, "in.json")
            self.assertEqual(run(["dwgread-exact", "-O", "JSON", "-o", src, dwg("line-001")]).returncode, 0)
            made = os.path.join(tmp, "made.dwg")
            r = run(["dwgwrite-exact", "--as", "r2000", "-o", made, src])
            self.assertEqual(r.returncode, 0, r.stderr)
            out = os.path.join(tmp, "read.json")
            self.assertEqual(run(["dwgdump", "--in", made, "--out", out]).returncode, 0)
            rec = load_json(out)
            self.assertEqual(rec["dwg_version"], "AC1015")
            ents = [b for b in rec["blocks"] if b["name"] == "*Model_Space"][0]["entities"]
            self.assertEqual([e["type"] for e in ents], ["LINE"])


if __name__ == "__main__":
    unittest.main()
