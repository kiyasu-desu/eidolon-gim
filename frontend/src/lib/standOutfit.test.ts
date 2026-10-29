import { afterEach, describe, expect, it, vi } from "vitest";
import {
  findOutfit,
  loadOutfitChoice,
  outfitsToTry,
  prefetchedFiles,
  readOutfitList,
  saveOutfitChoice,
  shouldPrefetch,
  wornOutfit,
  type OutfitCard,
} from "@/lib/standOutfit";

const KEY = "eidolon.standOutfits";
const LIST_URL = "https://stand.example/outfits/1.json";

/** This browser's local storage, in memory. */
function storage(initial: Record<string, string> = {}) {
  const items = new Map(Object.entries(initial));
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => items.get(key) ?? null,
    setItem: (key: string, value: string) => void items.set(key, value),
  });
  return items;
}

afterEach(() => vi.unstubAllGlobals());

/** An outfit as the list gives it, relative to the list. */
function listed(id: string) {
  return { id, url: `../${id}/`, thumbnail: `../thumbnails/${id}.png` };
}

/** An outfit as read from the list, resolved against it. */
function resolved(id: string) {
  return {
    id,
    url: `https://stand.example/${id}/`,
    thumbnail: `https://stand.example/thumbnails/${id}.png`,
  };
}

const DEFAULT = { id: "stand_3d/casual-1030010010", url: "https://stand.example/stand_3d/casual-1030010010/" };

const CARDS: OutfitCard[] = [
  {
    id: "1030010010",
    name: "ナチュラルモード",
    type: "P_SR",
    everyday: resolved("stand_3d/casual-1030010010"),
    stage: resolved("stand_3d/stage-1030010010"),
  },
  { id: "1040010010", name: "えっととスマイル", type: "Special", everyday: resolved("stand_3d/casual-1040010010"), stage: null },
];

describe("the outfit list", () => {
  it("reads her cards in the list's order, resolving each outfit against the list", () => {
    const list = {
      display_order: 1,
      cards: [
        {
          id: "1030010010",
          name: "ナチュラルモード",
          type: "P_SR",
          everyday: listed("stand_3d/casual-1030010010"),
          stage: listed("stand_3d/stage-1030010010"),
        },
        { id: "1040010010", name: "えっととスマイル", type: "Special", everyday: listed("stand_3d/casual-1040010010"), stage: null },
      ],
    };

    expect(readOutfitList(list, LIST_URL)).toEqual(CARDS);
  });

  it("leaves out a card with neither outfit, and an outfit written wrongly", () => {
    const list = {
      cards: [
        { id: "1", name: "a", type: "P_SR", everyday: null, stage: null },
        { id: "2", name: "b", type: "P_SR", everyday: { id: 3, url: "x/" }, stage: listed("stand_3d/stage-2") },
        { id: 4, name: "c", type: "P_SR", everyday: listed("stand_3d/casual-4"), stage: null },
        "not a card",
      ],
    };

    expect(readOutfitList(list, LIST_URL)).toEqual([
      { id: "2", name: "b", type: "P_SR", everyday: null, stage: resolved("stand_3d/stage-2") },
    ]);
  });

  it("is empty when the list is not one", () => {
    expect(readOutfitList(null, LIST_URL)).toEqual([]);
    expect(readOutfitList({ cards: "none" }, LIST_URL)).toEqual([]);
  });
});

describe("the outfit chosen on this device", () => {
  it("is none until one is chosen, then kept for each character apart, and replaced when she is given another", () => {
    storage();
    expect(loadOutfitChoice("sora")).toBeNull();

    saveOutfitChoice("sora", "stand_3d/stage-1030010010");
    saveOutfitChoice("riku", "stand_3d/casual-1040040010");

    expect(loadOutfitChoice("sora")).toBe("stand_3d/stage-1030010010");
    expect(loadOutfitChoice("riku")).toBe("stand_3d/casual-1040040010");

    saveOutfitChoice("sora", "stand_3d/casual-1040010010");

    expect(loadOutfitChoice("sora")).toBe("stand_3d/casual-1040010010");
    expect(loadOutfitChoice("riku")).toBe("stand_3d/casual-1040040010");
  });

  it("is none when what is stored cannot be read, and choosing again mends it", () => {
    storage({ [KEY]: "{not json" });

    expect(loadOutfitChoice("sora")).toBeNull();
    saveOutfitChoice("sora", "stand_3d/casual-1040010010");
    expect(loadOutfitChoice("sora")).toBe("stand_3d/casual-1040010010");
  });

  it("is none when what is stored for her is not an outfit, keeping the others", () => {
    storage({ [KEY]: JSON.stringify({ sora: 3, riku: "stand_3d/casual-1040040010" }) });

    expect(loadOutfitChoice("sora")).toBeNull();
    expect(loadOutfitChoice("riku")).toBe("stand_3d/casual-1040040010");
  });

  it("is none when what is stored is not a record of choices", () => {
    storage({ [KEY]: JSON.stringify(["stand_3d/casual-1040010010"]) });

    expect(loadOutfitChoice("sora")).toBeNull();
  });

  it("goes on without being remembered when storage is unavailable", () => {
    vi.stubGlobal("localStorage", {
      getItem: () => {
        throw new DOMException("denied", "SecurityError");
      },
      setItem: () => {
        throw new DOMException("denied", "SecurityError");
      },
    });

    expect(() => saveOutfitChoice("sora", "stand_3d/casual-1040010010")).not.toThrow();
    expect(loadOutfitChoice("sora")).toBeNull();
  });
});

describe("the outfit she wears", () => {
  it("is the one chosen, as the list gives it", () => {
    expect(wornOutfit("stand_3d/stage-1030010010", CARDS, DEFAULT, LIST_URL)).toEqual({
      id: "stand_3d/stage-1030010010",
      url: "https://stand.example/stand_3d/stage-1030010010/",
    });
  });

  it("is the default one when none is chosen", () => {
    expect(wornOutfit(null, CARDS, DEFAULT, LIST_URL)).toEqual(DEFAULT);
  });

  it("is the default one when the list no longer has the one chosen", () => {
    expect(wornOutfit("stand_3d/casual-9999999999", CARDS, DEFAULT, LIST_URL)).toEqual(DEFAULT);
  });

  it("is the one chosen, where the bucket keeps it, while the list is not to hand", () => {
    expect(wornOutfit("stand_3d/stage-1030010010", null, DEFAULT, LIST_URL)).toEqual({
      id: "stand_3d/stage-1030010010",
      url: "https://stand.example/stand_3d/stage-1030010010/",
    });
  });

  it("is the default one when what is chosen is not an outfit's name", () => {
    expect(wornOutfit("../../evil", null, DEFAULT, LIST_URL)).toEqual(DEFAULT);
    expect(wornOutfit("cb/1030010010", null, DEFAULT, LIST_URL)).toEqual(DEFAULT);
  });
});

describe("finding an outfit in the list", () => {
  it("gives its card and whether it is her everyday clothes or the stage costume", () => {
    expect(findOutfit(CARDS, "stand_3d/stage-1030010010")).toEqual({
      card: CARDS[0],
      look: "stage",
      outfit: resolved("stand_3d/stage-1030010010"),
    });
    expect(findOutfit(CARDS, "stand_3d/casual-1040010010")?.look).toBe("everyday");
  });

  it("gives nothing for an outfit the list does not have", () => {
    expect(findOutfit(CARDS, "stand_3d/casual-9999999999")).toBeNull();
  });
});

describe("the outfits a call tries", () => {
  it("are the one she wears, then the default one", () => {
    const worn = { id: "stand_3d/casual-1040010010", url: "https://stand.example/stand_3d/casual-1040010010/" };

    expect(outfitsToTry(worn, DEFAULT)).toEqual([worn, DEFAULT]);
  });

  it("are the default one alone when she wears it", () => {
    expect(outfitsToTry({ ...DEFAULT }, DEFAULT)).toEqual([DEFAULT]);
  });
});

describe("prefetching her stand", () => {
  it("happens unless the browser asks to save data", () => {
    expect(shouldPrefetch(undefined)).toBe(true);
    expect(shouldPrefetch({})).toBe(true);
    expect(shouldPrefetch({ saveData: false })).toBe(true);
    expect(shouldPrefetch({ saveData: true })).toBe(false);
  });

  it("does not prefetch an unsupported outfit", () => {
    expect(prefetchedFiles({ id: "unsupported", url: "/unused/" })).toEqual([]);
  });

  it("fetches model.json and animations.json for a 3D stand outfit without an external runtime", () => {
    const outfit3d = { id: "stand_3d/ttmr-default", url: "/api/characters/temari/stand/" };
    expect(prefetchedFiles(outfit3d)).toEqual([
      "/api/characters/temari/stand/model.json",
      "/api/characters/temari/stand/animations.json",
    ]);
  });
});
