// Public, non-secret configuration (a public SPA client has no secret).
window.STOCK_CONFIG = {
  region: "ap-south-1",
  cognitoDomain: "https://stock-dashboard-542601847637.auth.ap-south-1.amazoncognito.com",
  clientId: "7us8ffcbqlv94uoscmh57e5chu",
  apiBase: "https://sjdmkf8iag.execute-api.ap-south-1.amazonaws.com",
  // Must exactly match a callback URL registered on the Cognito app client.
  redirectUri: window.location.origin + "/",
  symbol: "AAPL",  // default ticker
  watchlist: ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"],
  modelSymbols: ["AAPL"],  // only these have an (experimental) model
};
