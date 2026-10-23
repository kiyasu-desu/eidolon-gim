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
  return { id, url: `../spine/idols/${id}/`, thumbnail: `../thumbnails/${id}.png` };
}

/** An outfit as read from the list, resolved against it. */
function resolved(id: string) {
  return {
    id,
    url: `https://stand.example/spine/idols/${id}/`,
    thumbnail: `https://stand.example/thumbnails/${id}.png`,
  };
}

const DEFAULT = { id: "stand/1030010010", url: "https://stand.example/spine/idols/stand/1030010010/" };

const CARDS: OutfitCard[] = [
  {
    id: "1030010010",
    name: "ナチュラルモード",
    type: "P_SR",
    everyday: resolved("stand/1030010010"),
    stage: resolved("stand_costume/1030010010"),
  },
  { id: "1040010010", name: "ほわっとスマイル", type: "Special", everyday: resolved("stand/1040010010"), stage: null },
];

describe("the outfit list", () => {
  it("reads her cards in the list's order, resolving each outfit against the list", () => {
    const list = {
      idol_id: 1,
      cards: [
        {
          id: "1030010010",
          name: "ナチュラルモード",
          type: "P_SR",
          everyday: listed("stand/1030010010"),
          stage: listed("stand_costume/1030010010"),
        },
        { id: "1040010010", name: "ほわっとスマイル", type: "Special", everyday: listed("stand/1040010010"), stage: null },
      ],
    };

    expect(readOutfitList(list, LIST_URL)).toEqual(CARDS);
  });

  it("leaves out a card with neither outfit, and an outfit written wrongly", () => {
    const list = {
      cards: [
        { id: "1", name: "a", type: "P_SR", everyday: null, stage: null },
        { id: "2", name: "b", type: "P_SR", everyday: { id: 3, url: "x/" }, stage: listed("stand_costume/2") },
        { id: 4, name: "c", type: "P_SR", everyday: listed("stand/4"), stage: null },
        "not a card",
      ],
    };

    expect(readOutfitList(list, LIST_URL)).toEqual([
      { id: "2", name: "b", type: "P_SR", everyday: null, stage: resolved("stand_costume/2") },
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
    expect(loadOutfitChoice("mano")).toBeNull();

    saveOutfitChoice("mano", "stand_costume/1030010010");
    saveOutfitChoice("kogane", "stand/1040040010");

    expect(loadOutfitChoice("mano")).toBe("stand_costume/1030010010");
    expect(loadOutfitChoice("kogane")).toBe("stand/1040040010");

    saveOutfitChoice("mano", "stand/1040010010");

    expect(loadOutfitChoice("mano")).toBe("stand/1040010010");
    expect(loadOutfitChoice("kogane")).toBe("stand/1040040010");
  });

  it("is none when what is stored cannot be read, and choosing again mends it", () => {
    storage({ [KEY]: "{not json" });

    expect(loadOutfitChoice("mano")).toBeNull();
    saveOutfitChoice("mano", "stand/1040010010");
    expect(loadOutfitChoice("mano")).toBe("stand/1040010010");
  });

  it("is none when what is stored for her is not an outfit, keeping the others", () => {
    storage({ [KEY]: JSON.stringify({ mano: 3, kogane: "stand/1040040010" }) });

    expect(loadOutfitChoice("mano")).toBeNull();
    expect(loadOutfitChoice("kogane")).toBe("stand/1040040010");
  });

  it("is none when what is stored is not a record of choices", () => {
    storage({ [KEY]: JSON.stringify(["stand/1040010010"]) });

    expect(loadOutfitChoice("mano")).toBeNull();
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

    expect(() => saveOutfitChoice("mano", "stand/1040010010")).not.toThrow();
    expect(loadOutfitChoice("mano")).toBeNull();
  });
});

describe("the outfit she wears", () => {
  it("is the one chosen, as the list gives it", () => {
    expect(wornOutfit("stand_costume/1030010010", CARDS, DEFAULT, LIST_URL)).toEqual({
      id: "stand_costume/1030010010",
      url: "https://stand.example/spine/idols/stand_costume/1030010010/",
    });
  });

  it("is the default one when none is chosen", () => {
    expect(wornOutfit(null, CARDS, DEFAULT, LIST_URL)).toEqual(DEFAULT);
  });

  it("is the default one when the list no longer has the one chosen", () => {
    expect(wornOutfit("stand/9999999999", CARDS, DEFAULT, LIST_URL)).toEqual(DEFAULT);
  });

  it("is the one chosen, where the bucket keeps it, while the list is not to hand", () => {
    expect(wornOutfit("stand_costume/1030010010", null, DEFAULT, LIST_URL)).toEqual({
      id: "stand_costume/1030010010",
      url: "https://stand.example/spine/idols/stand_costume/1030010010/",
    });
  });

  it("is the default one when what is chosen is not an outfit's name", () => {
    expect(wornOutfit("../../evil", null, DEFAULT, LIST_URL)).toEqual(DEFAULT);
    expect(wornOutfit("cb/1030010010", null, DEFAULT, LIST_URL)).toEqual(DEFAULT);
  });
});

describe("finding an outfit in the list", () => {
  it("gives its card and whether it is her everyday clothes or the stage costume", () => {
    expect(findOutfit(CARDS, "stand_costume/1030010010")).toEqual({
      card: CARDS[0],
      look: "stage",
      outfit: resolved("stand_costume/1030010010"),
    });
    expect(findOutfit(CARDS, "stand/1040010010")?.look).toBe("everyday");
  });

  it("gives nothing for an outfit the list does not have", () => {
    expect(findOutfit(CARDS, "stand/9999999999")).toBeNull();
  });
});

describe("the outfits a call tries", () => {
  it("are the one she wears, then the default one", () => {
    const worn = { id: "stand/1040010010", url: "https://stand.example/spine/idols/stand/1040010010/" };

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

  it("fetches the runtime and the files of the outfit she wears", () => {
    expect(prefetchedFiles(DEFAULT, "/vendor/spine-3.6/spine-webgl.js")).toEqual([
      "/vendor/spine-3.6/spine-webgl.js",
      "https://stand.example/spine/idols/stand/1030010010/data.json",
      "https://stand.example/spine/idols/stand/1030010010/data.atlas",
      "https://stand.example/spine/idols/stand/1030010010/data.png",
    ]);
  });

  it("fetches model.json and animations.json for a 3D stand outfit without the Spine runtime", () => {
    const outfit3d = { id: "stand_3d/ttmr-default", url: "/api/characters/temari/stand/" };
    expect(prefetchedFiles(outfit3d, "/vendor/spine-3.6/spine-webgl.js")).toEqual([
      "/api/characters/temari/stand/model.json",
      "/api/characters/temari/stand/animations.json",
    ]);
  });
});
