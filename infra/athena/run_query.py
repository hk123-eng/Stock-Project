"""Run one SQL statement in Athena workgroup stock-workgroup and print the rows and bytes scanned.
Usage: python infra/athena/run_query.py <file.sql | "SQL">   (profile stock-project, ap-south-1)"""
import pathlib
import sys
import time

import boto3

sql = sys.argv[1]
if sql.endswith(".sql"):
    sql = pathlib.Path(sql).read_text(encoding="utf-8")
ath = boto3.Session(profile_name="stock-project", region_name="ap-south-1").client("athena")
qid = ath.start_query_execution(QueryString=sql, WorkGroup="stock-workgroup",
                                QueryExecutionContext={"Database": "stock_project"})["QueryExecutionId"]
while True:
    q = ath.get_query_execution(QueryExecutionId=qid)["QueryExecution"]
    if q["Status"]["State"] not in ("QUEUED", "RUNNING"):
        break
    time.sleep(1)
st = q["Status"]
print(f"query {qid}: {st['State']} {st.get('StateChangeReason', '')}".strip())
print(f"bytes scanned: {q['Statistics'].get('DataScannedInBytes')}, engine ms: {q['Statistics'].get('EngineExecutionTimeInMillis')}")
if st["State"] == "SUCCEEDED" and q.get("StatementType") == "DML":
    rows = ath.get_query_results(QueryExecutionId=qid, MaxResults=100)["ResultSet"]["Rows"]
    for r in rows:
        print(" | ".join(c.get("VarCharValue", "") for c in r["Data"]))
sys.exit(0 if st["State"] == "SUCCEEDED" else 1)
