"use client";

export default function ApiBase() {
  // Inlined into the JS bundle by `next build`; changing it at runtime does nothing.
  return <p>API base: {process.env.NEXT_PUBLIC_API_BASE_URL ?? "(unset at build)"}</p>;
}
