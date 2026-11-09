"""BPI Challenge 2014 adapter on a few hand-made rows in the original file format."""

from app.ingestion.bpi2014 import build, write
from app.ingestion.loader import load_dataset
from app.ingestion.reader import read_dataset

INC_HEAD = ("CI Name (aff);CI Type (aff);CI Subtype (aff);Service Component WBS (aff);Incident ID;Status;Impact;Urgency;Priority;"
            "Category;KM number;Alert Status;# Reassignments;Open Time;Reopen Time;Resolved Time;Close Time;Handle Time (Hours);"
            "Closure Code;# Related Interactions;Related Interaction;# Related Incidents;# Related Changes;Related Change;"
            "CI Name (CBy);CI Type (CBy);CI Subtype (CBy);ServiceComp WBS (CBy)")


def _inc(i, wbs, prio, open_, resolved, closed, closure="Software", change="", category="incident"):
    return (f"WBA00{i};application;Web Based Application;{wbs};IM00000{i};Closed;{prio};{prio};{prio};{category};KM0001;closed;2;"
            f"{open_};;{resolved};{closed};1,5;{closure};1;SD1;0;{1 if change else ''};{change};WBA00{i};application;Web Based Application;{wbs}")


def _raw(tmp_path):
    rows = [
        _inc(1, "WBS000073", 3, "05/03/2014 09:00:00", "05/03/2014 13:00:00", "06/03/2014 09:00:00", change="C0000001"),
        _inc(2, "WBS000073", 4, "06/03/2014 10:00:00", "06/03/2014 11:00:00", "07/03/2014 10:00:00", closure="Hardware"),
        _inc(3, "WBS000091", 2, "07/03/2014 08:00:00", "07/03/2014 09:30:00", "07/03/2014 12:00:00", closure="Data"),
        _inc(4, "WBS000091", 5, "08/03/2014 08:00:00", "08/03/2014 08:30:00", "", closure="Other"),
        _inc(5, "WBS000091", 4, "08/03/2014 08:00:00", "08/03/2014 08:30:00", "", category="request for information"),
    ]
    (tmp_path / "Detail_Incident.csv").write_text(INC_HEAD + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    (tmp_path / "Detail_Incident_Activity.csv").write_text(
        "Incident ID;DateStamp;IncidentActivity_Number;IncidentActivity_Type;Assignment Group;KM number;Interaction ID\n"
        "IM000001;05-03-2014 09:10:00;A1;Assignment;TEAM0001;KM0001;SD1\n"
        "IM000001;05-03-2014 10:00:00;A2;Reassignment;TEAM0002;KM0001;SD1\n"
        "IM000003;07-03-2014 08:05:00;A3;Assignment;TEAM0003;KM0001;SD1\n", encoding="utf-8")
    (tmp_path / "Detail_Change.csv").write_text(
        "CI Name (aff);CI Type (aff);CI Subtype (aff);Service Component WBS (aff);Change ID;Change Type;Risk Assessment;Emergency Change;"
        "CAB-approval needed;Planned Start;Planned End;Scheduled Downtime Start;Scheduled Downtime End;Actual Start;Actual End;"
        "Requested End Date;Change record Open Time;Change record Close Time;Originated from;# Related Interactions;# Related Incidents\n"
        "WBA001;application;Web Based Application;WBS000073;C0000001;Release Type 11;Business Change;N;Y;5-3-2014 7:00;5-3-2014 8:00;;;"
        "5-3-2014 7:30;5-3-2014 8:00;5-3-2014 9:00;1-3-2014 9:00;5-3-2014 9:00;Problem;;1\n"
        "WBA002;application;Web Based Application;WBS000091;C0000002;Standard Change Type 81;Minor Change;Y;N;1-3-2014 7:00;1-3-2014 8:00;;;"
        "1-3-2014 7:30;1-3-2014 8:00;1-3-2014 9:00;1-2-2014 9:00;1-3-2014 9:00;Problem;;\n", encoding="utf-8")
    return tmp_path


def test_mapping(tmp_path):
    ds = build(_raw(tmp_path))
    assert ds["manifest"]["data_source"] == "BPI2014" and "4TU" in ds["manifest"]["license"]
    assert {a["code"] for a in ds["applications"]} == {"BPI-W000073", "BPI-W000091"}
    incs = {i["external_id"]: i for i in ds["incidents"]}
    assert set(incs) == {"IM000001", "IM000002", "IM000003", "IM000004"}  # information request excluded
    assert incs["IM000001"]["severity"] == "P3" and incs["IM000003"]["severity"] == "P2" and incs["IM000004"]["severity"] == "P4"
    assert incs["IM000002"]["category"] == "INFRASTRUCTURE" and incs["IM000003"]["category"] == "DATA_PROCESSING"
    first = incs["IM000001"]["history"]
    assert first[0] == {"type": "assign", "after_minutes": 10.0, "team": "TEAM0001", "actor": "bpi2014.import"}
    assert any(s.get("description", "").startswith("BPI activity: Reassignment") for s in first)
    assert [s["status"] for s in first if s["type"] == "status"][-2:] == ["RESOLVED", "CLOSED"]
    assert incs["IM000001"]["change_links"][0]["change_reference"] == "C0000001"
    kinds = {c["change_reference"]: (c["change_type"], c["risk_level"]) for c in ds["changes"]}
    assert kinds == {"C0000001": ("NORMAL", "MEDIUM"), "C0000002": ("EMERGENCY", "LOW")}


def test_subset_loads_through_ingestion(db, tmp_path):
    out = tmp_path / "ds"
    write(build(_raw(tmp_path)), out)
    report = load_dataset(db, read_dataset(out))
    assert report.counts["incidents"] == 4 and report.counts["changes"] == 2
