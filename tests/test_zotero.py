"""The Bibliography of South Asian Ornithology (pipeline/zotero.py): papers per bird name from the public Zotero
group, fetched once in full and then only what changed."""

import json

from pipeline import zotero


def item(key, version, tags, date="2009", kind="journalArticle", parent=None):
    data = {"key": key, "version": version, "itemType": kind, "date": date, "tags": [{"tag": t} for t in tags]}
    if parent:
        data["parentItem"] = parent
    return {"key": key, "version": version, "data": data}


class Resp:
    def __init__(self, body, headers):
        self.body, self.headers, self.status_code = body, headers, 200

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


class FakeZotero:
    """A library at `version`: items served `limit` at a time, modified since a version; deleted keys since one."""

    def __init__(self, items, version, deleted=None):
        self.items, self.version, self.deleted, self.calls = items, version, deleted or {}, []

    def get(self, url, params=None, **kw):
        self.calls.append((url, dict(params or {})))
        since = int(params.get("since", 0))
        if url.endswith("/deleted"):
            return Resp({"items": [k for k, v in self.deleted.items() if v > since]}, {"Last-Modified-Version": str(self.version)})
        rows = [i for i in self.items if i["version"] > since]
        start, limit = int(params["start"]), int(params["limit"])
        return Resp(rows[start:start + limit], {"Last-Modified-Version": str(self.version), "Total-Results": str(len(rows))})


def test_species_tags_become_names_and_other_tags_stay_out():
    assert zotero.names_of(["BUBO BENGALENSIS", "INDIA", "SRI LANKA", "ACCIPITRIDAE", "MISSING ENTRY",
                            "GALLUS GALLUS MURGHI", "ANDAMAN & NICOBAR ISLANDS"]) == [
        "Bubo bengalensis", "Sri lanka", "Missing entry", "Gallus gallus murghi"]


def test_a_full_pass_then_only_changes_and_deletions(tmp_path):
    lib = FakeZotero([item("A", 1, ["BUBO BENGALENSIS", "INDIA"], "2009"),
                      item("B", 2, ["BUBO BENGALENSIS"], "Mar 2015"),
                      item("N", 3, [], kind="note"), item("C", 3, ["ALCEDO MENINTING"], "2001", parent="A"),
                      item("D", 4, ["ALCEDO MENINTING"], "")], version=4)
    state = {}
    assert zotero.sync(lib, state, page=2)
    assert state["version"] == 4 and set(state["items"]) == {"A", "B", "D"}       # no notes, no child items
    assert state["items"]["B"] == [2015, ["BUBO BENGALENSIS"]] and state["items"]["D"] == [None, ["ALCEDO MENINTING"]]
    lib.items.append(item("E", 5, ["BUBO BENGALENSIS"], "2024"))
    lib.version, lib.deleted = 6, {"A": 6}
    n = len(lib.calls)
    assert zotero.sync(lib, state, page=2)
    assert set(state["items"]) == {"B", "D", "E"} and state["version"] == 6
    assert all(c[1].get("since") == 4 for c in lib.calls[n:])                     # asked only for changes


def test_a_stopped_pass_continues_where_it_stopped(tmp_path):
    lib = FakeZotero([item(k, 1, ["BUBO BENGALENSIS"]) for k in "ABCDEF"], version=1)
    state = {}
    assert not zotero.sync(lib, state, page=2, deadline=0)                         # stopped before any page
    assert not zotero.sync(lib, state, page=2, pages=1)                            # one page, then stopped
    assert state["pending"]["start"] == 2 and len(state["items"]) == 2
    assert zotero.sync(lib, state, page=2)
    assert len(state["items"]) == 6 and "pending" not in state and state["version"] == 1


def test_table_counts_papers_and_years_per_name(tmp_path):
    state = {"version": 9, "items": {"A": [2009, ["BUBO BENGALENSIS", "INDIA"]], "B": [2015, ["BUBO BENGALENSIS"]],
                                     "C": [None, ["BUBO BENGALENSIS"]], "D": [2001, ["ALCEDO MENINTING"]]}}
    path = zotero.write_table(state, tmp_path / "t.csv")
    rows = path.read_text().splitlines()
    assert rows[0] == "name,papers,first_year,latest_year"
    assert "Bubo bengalensis,3,2009,2015" in rows and "Alcedo meninting,1,2001,2001" in rows


def test_refresh_keeps_the_state_in_r2_and_a_new_machine_continues_from_it(tmp_path, monkeypatch):
    from tests.r2_fake import FakeS3
    monkeypatch.setenv("R2_BUCKET", "b")
    lib = FakeZotero([item("A", 1, ["BUBO BENGALENSIS"], "2009")], version=1)
    s3 = FakeS3()
    table = zotero.refresh(lib, s3, tmp_path / "one")
    assert table.read_text().splitlines()[1] == "Bubo bengalensis,1,2009,2009"
    assert {zotero.R2_DIR + "state.json", zotero.R2_DIR + zotero.TABLE} <= set(s3.store)
    n = len(lib.calls)
    zotero.refresh(lib, s3, tmp_path / "two")
    assert all(c[1].get("since") == 1 for c in lib.calls[n:])
    assert json.loads((tmp_path / "two" / "state.json").read_text())["version"] == 1
