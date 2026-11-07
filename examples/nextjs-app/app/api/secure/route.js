export function GET(request) {
  const secret = process.env.API_SECRET;
  if (!secret) {
    return Response.json({ error: "API_SECRET not configured" }, { status: 500 });
  }
  if (request.headers.get("authorization") !== `Bearer ${secret}`) {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }
  return Response.json({ ok: true });
}
