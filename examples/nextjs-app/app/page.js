import { connection } from "next/server";
import ApiBase from "./api-base";

export default async function Home() {
  // Opt out of prerendering so GREETING is read per request, at runtime.
  await connection();
  const greeting = process.env.GREETING ?? "Hello";
  return (
    <main>
      <h1>{greeting} from nextjs-app</h1>
      <ApiBase />
    </main>
  );
}
