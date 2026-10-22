"""Direct-invoke regression test of every stock-api route. Usage: route_tests.py [qualifier]"""
import json, sys, boto3
lam = boto3.Session(profile_name="stock-project", region_name="ap-south-1").client("lambda")
Q = sys.argv[1] if len(sys.argv) > 1 else None
def call(path, qs=None, method="GET", claims=None):
    ev = {"rawPath": path, "requestContext": {"http": {"method": method}}, "queryStringParameters": qs}
    if claims: ev["requestContext"]["authorizer"] = {"jwt": {"claims": claims}}
    kw = {"FunctionName": "stock-api", "Payload": json.dumps(ev)}
    if Q: kw["Qualifier"] = Q
    r = json.loads(lam.invoke(**kw)["Payload"].read())
    return r["statusCode"], json.loads(r["body"])
cases = [
    ("/prices", {"symbol": "AAPL", "limit": "5"}, 200), ("/prices/latest", {"symbol": "NVDA"}, 200),
    ("/prices/synthetic", {"symbol": "AAPL", "limit": "5"}, 200), ("/predictions", {"symbol": "AAPL"}, 200),
    ("/predictions/latest", {"symbol": "AAPL"}, 200), ("/signals", {"symbol": "MSFT", "limit": "1"}, 200),
    ("/alerts", {"symbol": "GOOGL"}, 200), ("/evaluation", {"symbol": "AAPL"}, 200), ("/model-health", {"symbol": "AAPL"}, 200),
    ("/predictions/latest", {"symbol": "NVDA"}, 404), ("/prices", {"symbol": "TSLA"}, 400), ("/prices", {"limit": "0"}, 400),
    ("/nope", None, 404),
]
bad = 0
for path, qs, want in cases:
    st, body = call(path, qs)
    ok = st == want; bad += not ok
    print(f"{'OK ' if ok else 'BAD'} {path} {qs} -> {st} (want {want})")
st, _ = call("/prices", {"symbol": "AAPL"}, method="POST"); bad += st != 405; print(f"{'OK ' if st == 405 else 'BAD'} POST /prices -> {st}")
st, body = call("/me", claims={"email": "test@example.com", "cognito:groups": "[viewer]", "sub": "x"})
ok = st == 200 and body == {"email": "test@example.com", "cognito:groups": ["viewer"]}; bad += not ok
print(f"{'OK ' if ok else 'BAD'} /me (claims) -> {st} {body}")
st, body = call("/me"); bad += st != 401; print(f"{'OK ' if st == 401 else 'BAD'} /me (no claims) -> {st}")
print("FAILURES", bad); sys.exit(1 if bad else 0)
