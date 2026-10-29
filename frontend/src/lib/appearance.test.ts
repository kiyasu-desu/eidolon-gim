import { afterEach, describe, expect, it, vi } from "vitest";

import type { Character } from "@/lib/api";
import { DEFAULT_APPEARANCE, keepAppearance, loadAppearance, withAppearance } from "@/lib/appearance";

/** 这个浏览器的 localStorage，放在内存里。 */
function storage(initial: Record<string, string> = {}) {
  const items = new Map(Object.entries(initial));
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => items.get(key) ?? null,
    setItem: (key: string, value: string) => void items.set(key, value),
  });
  return items;
}

afterEach(() => vi.unstubAllGlobals());

const character = (id: string, alternate: boolean) =>
  ({
    id,
    avatar_url: `/api/characters/${id}/avatar`,
    alternate_avatar_url: alternate ? `/api/characters/${id}/alternate-avatar` : null,
  }) as Character;

describe("外观存在这台设备上、按用户分开", () => {
  it("没存过时 alternate 头像是关的", () => {
    storage();
    expect(loadAppearance("u1")).toEqual(DEFAULT_APPEARANCE);
    expect(DEFAULT_APPEARANCE.alternateAvatars).toBe(false);
  });

  it("存下的读得回来，别的用户读不到", () => {
    storage();
    keepAppearance("u1", { alternateAvatars: true });
    expect(loadAppearance("u1")).toEqual({ alternateAvatars: true });
    expect(loadAppearance("u2")).toEqual({ alternateAvatars: false });
  });

  it("数据坏了当作默认", () => {
    storage({ "eidolon.appearance.u1": "{oops", "eidolon.appearance.u2": '{"alternateAvatars":"yes"}' });
    expect(loadAppearance("u1")).toEqual(DEFAULT_APPEARANCE);
    expect(loadAppearance("u2")).toEqual(DEFAULT_APPEARANCE);
  });

  it("存不进去时不抛错", () => {
    vi.stubGlobal("localStorage", {
      setItem: () => {
        throw new Error("QuotaExceededError");
      },
    });
    expect(() => keepAppearance("u1", { alternateAvatars: true })).not.toThrow();
  });
});

describe("按外观换头像", () => {
  const all = [character("sora", true), character("riku", false)];

  it("关着时头像照旧", () => {
    expect(withAppearance(all, { alternateAvatars: false })).toBe(all);
  });

  it("打开时换成她的 alternate 头像，她没有的照旧", () => {
    expect(withAppearance(all, { alternateAvatars: true }).map((c) => c.avatar_url)).toEqual([
      "/api/characters/sora/alternate-avatar",
      "/api/characters/riku/avatar",
    ]);
  });
});
