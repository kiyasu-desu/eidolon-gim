import { afterEach, describe, expect, it, vi } from "vitest";

import {
  hide,
  keepListPreferences,
  listPreferences,
  NO_PREFERENCES,
  pin,
  setShown,
  show,
  showAll,
  unpin,
} from "@/lib/listPreferences";

// 配置里现有的角色。
const KNOWN = ["sora", "nagi", "hina", "riku", "mina"];

/** 这个浏览器的 localStorage，放在内存里。 */
function storage(initial: Record<string, string> = {}) {
  const items = new Map(Object.entries(initial));
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => items.get(key) ?? null,
    setItem: (key: string, value: string) => void items.set(key, value),
    removeItem: (key: string) => void items.delete(key),
  });
  return items;
}

afterEach(() => vi.unstubAllGlobals());

describe("这台设备上的隐藏和置顶", () => {
  it("按用户分开存，存下的读回来一样", () => {
    storage();

    keepListPreferences("u1", pin(hide(NO_PREFERENCES, ["mina"]), "sora"));
    keepListPreferences("u2", hide(NO_PREFERENCES, ["nagi"]));

    expect(listPreferences("u1", KNOWN)).toEqual({ hidden: ["mina"], pinned: ["sora"] });
    expect(listPreferences("u2", KNOWN)).toEqual({ hidden: ["nagi"], pinned: [] });
    expect(listPreferences("u3", KNOWN)).toEqual(NO_PREFERENCES);
  });

  it("配置里已经不存在的角色读的时候忽略", () => {
    storage({ "eidolon.listPreferences.u1": JSON.stringify({ hidden: ["gone", "nagi"], pinned: ["left", "sora"] }) });

    expect(listPreferences("u1", KNOWN)).toEqual({ hidden: ["nagi"], pinned: ["sora"] });
  });

  it("数据坏了当作什么都没整理", () => {
    storage({
      "eidolon.listPreferences.u1": "{not json",
      "eidolon.listPreferences.u2": JSON.stringify(["sora"]),
      "eidolon.listPreferences.u3": JSON.stringify({ hidden: "sora", pinned: [42, "nagi"] }),
    });

    expect(listPreferences("u1", KNOWN)).toEqual(NO_PREFERENCES);
    expect(listPreferences("u2", KNOWN)).toEqual(NO_PREFERENCES);
    expect(listPreferences("u3", KNOWN)).toEqual({ hidden: [], pinned: ["nagi"] });
  });

  it("存储用不了时不抛错，读到的是什么都没整理", () => {
    const unreachable = () => {
      throw new DOMException("denied", "SecurityError");
    };
    vi.stubGlobal("localStorage", { getItem: unreachable, setItem: unreachable, removeItem: unreachable });

    expect(() => keepListPreferences("u1", hide(NO_PREFERENCES, ["sora"]))).not.toThrow();
    expect(listPreferences("u1", KNOWN)).toEqual(NO_PREFERENCES);
  });

});

describe("整理列表", () => {
  it("隐藏一位置顶的角色，她的置顶一并取消", () => {
    const pinned = pin(NO_PREFERENCES, "sora");

    expect(hide(pinned, ["sora"])).toEqual({ hidden: ["sora"], pinned: [] });
  });

  it("置顶一位隐藏的角色，她同时恢复显示", () => {
    const hidden = hide(NO_PREFERENCES, ["sora", "nagi"]);

    expect(pin(hidden, "sora")).toEqual({ hidden: ["nagi"], pinned: ["sora"] });
  });

  it("setShown 按勾没勾显示或隐藏", () => {
    expect(setShown(NO_PREFERENCES, ["sora"], false)).toEqual({ hidden: ["sora"], pinned: [] });
    expect(setShown(hide(NO_PREFERENCES, ["sora"]), ["sora"], true)).toEqual(NO_PREFERENCES);
  });

  it("显示和取消置顶只动那一位", () => {
    const prefs = pin(pin(hide(NO_PREFERENCES, ["hina", "riku"]), "sora"), "nagi");

    expect(show(prefs, ["hina"])).toEqual({ hidden: ["riku"], pinned: ["sora", "nagi"] });
    expect(unpin(prefs, "sora")).toEqual({ hidden: ["hina", "riku"], pinned: ["nagi"] });
  });

  it("整组隐藏、整组显示", () => {
    const prefs = pin(hide(NO_PREFERENCES, ["sora"]), "hina");
    const illumination = ["sora", "nagi", "hina"];

    const hidden = hide(prefs, illumination);
    expect(hidden).toEqual({ hidden: ["sora", "nagi", "hina"], pinned: [] });
    expect(show(hidden, illumination)).toEqual(NO_PREFERENCES);
  });

  it("重复隐藏、重复置顶不会多记", () => {
    expect(hide(hide(NO_PREFERENCES, ["sora"]), ["sora"])).toEqual({ hidden: ["sora"], pinned: [] });
    expect(pin(pin(NO_PREFERENCES, "sora"), "sora")).toEqual({ hidden: [], pinned: ["sora"] });
  });

  it("「全部显示」只清空隐藏，置顶不变", () => {
    const prefs = pin(hide(NO_PREFERENCES, ["nagi", "riku"]), "sora");

    expect(showAll(prefs)).toEqual({ hidden: [], pinned: ["sora"] });
  });
});
