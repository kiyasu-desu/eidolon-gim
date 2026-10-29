import { describe, expect, it } from "vitest";
import type { Character, Memory } from "@/lib/api";
import { sourceCharacter, supersededMark } from "@/lib/memories";

const sora: Character = {
  id: "sora",
  name: "星野ソラ",
  intro: "",
  avatar_url: "/api/characters/sora/avatar",
  alternate_avatar_url: null,
  color: "#ffbad6",
  background_url: null,
  stand: null,
  display_order: 1,
  name_zh: null,
  name_kana: null,
  name_romaji: null,
  unit: null,
  unit_reading: null,
  unit_order: null,
  greeting: null,
  call_opener: null,
};

const memory = (source: string, superseded = false): Memory => ({
  id: 1,
  text: "制作人喜欢喝咖啡",
  source_character_id: source,
  source_character_name: source === "sora" ? "星野ソラ" : null,
  created_at: "2026-09-01T12:00:00Z",
  superseded,
});

describe("sourceCharacter", () => {
  it("找到记忆的来源角色，界面才能用她的颜色和头像标出来", () => {
    expect(sourceCharacter(memory("sora"), [sora])).toBe(sora);
  });

  it("来源角色已经不在配置里时没有角色", () => {
    expect(sourceCharacter(memory("nagi"), [sora])).toBeNull();
  });

  it("角色列表还没取到时也没有角色", () => {
    expect(sourceCharacter(memory("sora"), [])).toBeNull();
  });
});

describe("supersededMark", () => {
  it("被取代的记忆标出「已被取代」", () => {
    expect(supersededMark(memory("sora", true))).toBe("已被取代");
  });

  it("有效的记忆不标", () => {
    expect(supersededMark(memory("sora"))).toBeNull();
  });
});
