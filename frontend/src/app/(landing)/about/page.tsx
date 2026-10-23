import type { Metadata } from "next";
import { cookies } from "next/headers";

import { getSignInOptions, isSignedIn } from "@/lib/backend";

import { Landing } from "../Landing";

export const metadata: Metadata = {
  alternates: { canonical: "/" },
};

/** `/about`：已登录也能查看产品范围，入口换成「继续」。 */
export default async function About() {
  const [signedIn, signInOptions] = await Promise.all([
    isSignedIn((await cookies()).toString()),
    getSignInOptions(),
  ]);
  return <Landing isSignedIn={signedIn} signInOptions={signInOptions} />;
}
