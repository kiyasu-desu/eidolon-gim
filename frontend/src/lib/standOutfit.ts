// Her outfits (GLOSSARY.md「衣装」, spec「衣装与换衣装」): the outfit list the deployment
// publishes for her, the outfit chosen for her on this device, and which outfit a call puts
// her in. The choice is kept in this browser's local storage, one outfit per character.

import type { Outfit } from "@/lib/api";
import { is3DStandOutfit } from "@/lib/stand3d";

/** An outfit as the outfit list gives it, with its thumbnail. */
export type ListedOutfit = Outfit & { thumbnail: string };

/** Which of a card's outfits: her everyday clothes on it, or its stage costume. */
export type Look = "everyday" | "stage";

export const LOOKS: readonly Look[] = ["everyday", "stage"];

/** One of her cards: her everyday clothes on it and its stage costume, either of which it may
 * lack (a card whose two are the same is listed with its everyday clothes alone). */
export type OutfitCard = {
  /** The card's enzaId. */
  id: string;
  /** The card's name as in the game, without the 【】 or her name. */
  name: string;
  /** Its rarity or kind: P_SSR, Special... */
  type: string;
  everyday: ListedOutfit | null;
  stage: ListedOutfit | null;
};

/**
 * Her cards, in the order the list gives them (the order the game released them), from the
 * outfit list at `listUrl` (docs/deploy.md「立绘素材」). The list's `url`s and `thumbnail`s are
 * relative to it; here they are resolved against `listUrl`, which must be absolute. What is
 * written wrongly is left out, and so is a card left with no outfit.
 */
export function readOutfitList(list: unknown, listUrl: string): OutfitCard[] {
  const cards = isRecord(list) && Array.isArray(list.cards) ? list.cards : [];
  const read: OutfitCard[] = [];
  for (const card of cards) {
    if (!isRecord(card) || !isString(card.id) || !isString(card.name) || !isString(card.type)) continue;
    const everyday = readOutfit(card.everyday, listUrl);
    const stage = readOutfit(card.stage, listUrl);
    if (everyday || stage) read.push({ id: card.id, name: card.name, type: card.type, everyday, stage });
  }
  return read;
}

function readOutfit(outfit: unknown, listUrl: string): ListedOutfit | null {
  if (!isRecord(outfit) || !isString(outfit.id) || !isString(outfit.url) || !isString(outfit.thumbnail)) return null;
  try {
    return {
      id: outfit.id,
      url: new URL(outfit.url, listUrl).href,
      thumbnail: new URL(outfit.thumbnail, listUrl).href,
    };
  } catch {
    return null;
  }
}

const STORAGE_KEY = "eidolon.standOutfits";

/** The outfit chosen for her on this device (`stand/<enzaId>` or `stand_costume/<enzaId>`);
 * null when none is, or what is stored cannot be read. */
export function loadOutfitChoice(characterId: string): string | null {
  const choice = loadChoices()[characterId];
  return isString(choice) ? choice : null;
}

/** Remember the outfit chosen for her, keeping the others'. Whether it still loads does not
 * matter here: a call that cannot load it falls back without forgetting it. */
export function saveOutfitChoice(characterId: string, outfitId: string): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...loadChoices(), [characterId]: outfitId }));
  } catch {
    // Storage unavailable (e.g. private mode): the choice just won't be remembered.
  }
}

function loadChoices(): Record<string, unknown> {
  try {
    const stored: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}");
    return isRecord(stored) ? stored : {};
  } catch {
    return {};
  }
}

/** Where an outfit is in her list: its card, and which of the card's outfits it is. */
export function findOutfit(
  cards: readonly OutfitCard[],
  outfitId: string,
): { card: OutfitCard; look: Look; outfit: ListedOutfit } | null {
  for (const card of cards) {
    for (const look of LOOKS) {
      const outfit = card[look];
      if (outfit?.id === outfitId) return { card, look, outfit };
    }
  }
  return null;
}

/** An outfit's name as the bucket lays it out: `stand/<enzaId>` or `stand_costume/<enzaId>`. */
const OUTFIT_ID = /^stand(_costume)?\/\d+$/;

/**
 * The outfit she wears: the one chosen for her, as her outfit list (`cards`) gives it; her
 * default outfit when none is chosen, or when the list no longer has the one chosen. While the
 * list (null) is not to hand, the one chosen is found where the bucket keeps it beside the list
 * at `listUrl` (docs/deploy.md「立绘素材」), so that a call dialled early or while the list cannot
 * be read still tries it first.
 */
export function wornOutfit(
  choice: string | null,
  cards: readonly OutfitCard[] | null,
  fallback: Outfit,
  listUrl: string,
): Outfit {
  if (choice === null) return fallback;
  if (cards) {
    const found = findOutfit(cards, choice);
    return found ? { id: found.outfit.id, url: found.outfit.url } : fallback;
  }
  if (!OUTFIT_ID.test(choice)) return fallback;
  return { id: choice, url: new URL(`../spine/idols/${choice}/`, listUrl).href };
}

/** The outfits a call tries, in order (spec「通话层」): the one she wears, then her default
 * outfit; after both, her call background alone. */
export function outfitsToTry(worn: Outfit, fallback: Outfit): Outfit[] {
  return worn.url === fallback.url ? [fallback] : [worn, fallback];
}

/** Whether to prefetch her stand while the browser is idle: not when it asks to save data
 * (`navigator.connection.saveData`), when the stand downloads as the call is dialled. */
export function shouldPrefetch(connection: { saveData?: boolean } | undefined): boolean {
  return connection?.saveData !== true;
}

/** What prefetching her stand fetches: the runtime at `runtimeUrl`, and the files of the
 * outfit she wears (or `model.json` and `animations.json` for a 3D stand). */
export function prefetchedFiles(outfit: Pick<Outfit, "id" | "url">, runtimeUrl: string): string[] {
  if (is3DStandOutfit(outfit)) {
    return ["model.json", "animations.json"].map((file) => `${outfit.url}${file}`);
  }
  return [runtimeUrl, ...["data.json", "data.atlas", "data.png"].map((file) => `${outfit.url}${file}`)];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isString(value: unknown): value is string {
  return typeof value === "string";
}
