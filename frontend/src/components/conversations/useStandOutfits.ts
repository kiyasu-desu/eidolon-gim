"use client";

import { useEffect, useState } from "react";

import type { Character, Outfit } from "@/lib/api";
import {
  loadOutfitChoice,
  outfitsToTry,
  prefetchedFiles,
  readOutfitList,
  saveOutfitChoice,
  shouldPrefetch,
  wornOutfit,
  type OutfitCard,
} from "@/lib/standOutfit";


export type StandOutfits = {
  /** 她的卡片，按衣装清单的顺序；清单还在读时为 null。 */
  cards: OutfitCard[] | null;
  /** 衣装清单这次没读到（`cards` 为空）。 */
  isListFailed: boolean;
  /** 她穿的那套：选中的，没选过或者清单里没有了是默认衣装。 */
  worn: Outfit;
  /** 通话时立绘依次试的衣装：她穿的那套，再是默认衣装。 */
  toTry: Outfit[];
  /** 换上这一套（记在这台设备上）。 */
  wear: (outfitId: string) => void;
  /** 清单没读到时再读一次。 */
  reloadList: () => void;
};

/**
 * 她的衣装（spec「衣装与换衣装」）：读她的衣装清单，读写这台设备上为她选的那套，定下她穿哪套
 * （清单还没到或者读不到时，按存储桶的布局找选中的那套，见 `wornOutfit`）。
 * 读到选择之后，趁浏览器空闲把 runtime 和她穿的那套预取进缓存；开了省流量就不预取，
 * 等按下打电话键再下载。她没有立绘时返回 null。
 */
export function useStandOutfits(character: Character): StandOutfits | null {
  const { id: characterId, stand } = character;
  const listUrl = stand?.outfits_url ?? null;
  const [choice, setChoice] = useState<{ characterId: string; outfitId: string | null } | null>(null);
  const [list, setList] = useState<{ url: string; cards: OutfitCard[] | null; attempt: number } | null>(null);
  const [attempt, setAttempt] = useState(0);

  // 本机存的选择只在浏览器里读得到，挂载后再读。
  useEffect(() => {
    setChoice({ characterId, outfitId: loadOutfitChoice(characterId) });
  }, [characterId]);

  useEffect(() => {
    if (!listUrl) return;
    const url = absolute(listUrl);
    let current = true;
    fetch(url)
      .then((response) => {
        if (!response.ok) throw new Error(`衣装清单 ${response.status}`);
        return response.json();
      })
      .then(
        (json: unknown) => current && setList({ url: listUrl, cards: readOutfitList(json, url), attempt }),
        () => current && setList({ url: listUrl, cards: null, attempt }),
      );
    return () => {
      current = false;
    };
  }, [listUrl, attempt]);

  const outfitId = choice?.characterId === characterId ? choice.outfitId : null;
  const settled = list?.url === listUrl && list.attempt === attempt ? list : null;
  const cards = settled?.cards ?? null;
  const worn = stand && listUrl ? wornOutfit(outfitId, cards, stand.default_outfit, absolute(listUrl)) : null;

  // 读到本机的选择就预取她穿的那套，不等清单；清单到了发现这套已经没有了、或者换了衣装，就预取新的那套。
  // 单套默认立绘（没有衣装清单 `outfits_url`）也在空闲时预取默认立绘。
  const prefetchOutfit =
    choice?.characterId === characterId ? (worn ?? stand?.default_outfit ?? null) : null;
  const prefetchId = prefetchOutfit?.id ?? null;
  const prefetchUrl = prefetchOutfit?.url ?? null;
  useEffect(() => {
    if (!prefetchId || !prefetchUrl || !shouldPrefetch(connection())) return;
    const files = prefetchedFiles({ id: prefetchId, url: prefetchUrl });
    return whenIdle(() => {
      // 读完响应体才算进了缓存；预取失败无所谓，打电话时再下载。
      for (const file of files) fetch(file).then((response) => response.arrayBuffer()).catch(() => {});
    });
  }, [prefetchId, prefetchUrl]);

  if (!stand || !worn) return null;
  return {
    cards: settled ? (settled.cards ?? []) : null,
    isListFailed: settled !== null && settled.cards === null,
    worn,
    toTry: outfitsToTry(worn, stand.default_outfit),
    wear: (id) => {
      saveOutfitChoice(characterId, id);
      setChoice({ characterId, outfitId: id });
    },
    reloadList: () => setAttempt((n) => n + 1),
  };
}

/** 清单的绝对地址：后端给的一般已经是绝对地址，相对的按当前页面算。 */
function absolute(url: string): string {
  return new URL(url, typeof window === "undefined" ? undefined : window.location.href).href;
}

/** 浏览器的网络信息（`navigator.connection`），不是所有浏览器都有。 */
function connection(): { saveData?: boolean } | undefined {
  return (navigator as Navigator & { connection?: { saveData?: boolean } }).connection;
}

/** 浏览器空闲时执行；Safari 没有 requestIdleCallback，稍后执行。返回取消的函数。 */
function whenIdle(run: () => void): () => void {
  if (typeof window.requestIdleCallback === "function") {
    const handle = window.requestIdleCallback(run, { timeout: IDLE_TIMEOUT_MS });
    return () => window.cancelIdleCallback(handle);
  }
  const handle = window.setTimeout(run, IDLE_FALLBACK_MS);
  return () => window.clearTimeout(handle);
}

/** 一直不空闲时，最迟这么久之后也预取（毫秒）。 */
const IDLE_TIMEOUT_MS = 5000;
/** 没有 requestIdleCallback 时，打开对话页这么久之后预取（毫秒）。 */
const IDLE_FALLBACK_MS = 2000;
