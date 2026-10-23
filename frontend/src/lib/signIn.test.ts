import { describe, expect, it } from "vitest";
import { linkUrl, signInFailure, signInUrl } from "@/lib/signIn";

describe("signInFailure", () => {
  it("says nothing when signing in did not fail", () => {
    expect(signInFailure(null)).toBeNull();
    expect(signInFailure("")).toBeNull();
  });

  it("explains each reason the backend gives", () => {
    expect(signInFailure("too_new")).toContain("一年");
    expect(signInFailure("email_unverified")).toContain("验证");
    expect(signInFailure("banned")).toContain("封禁");
    expect(signInFailure("not_allowed")).toContain("白名单");
    expect(signInFailure("taken")).toContain("另一位用户");
  });

  it("tells a banned user how to reach the deployer, when the deployer says how", () => {
    expect(signInFailure("banned", "admin@example.com")).toContain("admin@example.com");
    expect(signInFailure("banned", null)).toBe(signInFailure("banned"));
    expect(signInFailure("too_new", "admin@example.com")).not.toContain("admin@example.com");
  });

  it("still says signing in failed for a reason it does not know", () => {
    expect(signInFailure("something_new")).toBe("登录失败，请重新登录。");
  });
});

describe("signInUrl", () => {
  it("starts at the backend, which sends the browser on to the provider", () => {
    expect(signInUrl("github")).toBe("/api/auth/github/start");
    expect(linkUrl("google")).toBe("/api/auth/google/start?link=1");
  });
});
