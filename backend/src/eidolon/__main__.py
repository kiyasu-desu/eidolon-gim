"""Eidolon-GIM: serve, users, local story packs, speech, backups and evaluation."""

import argparse
import asyncio
import logging
import os
import sqlite3
import sys
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from eidolon.clock import utc_now
from eidolon.config import (
    JUDGE_PROVIDERS,
    Settings,
    UsageLimits,
    characters_path_from_env,
    database_path_from_env,
    story_database_path_from_env,
    stories_enabled_from_env,
)
from eidolon.identity import PROVIDER_LABELS
from eidolon.store import NotFound, Store
from eidolon.usage import Tally, UsageLimiter


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command in (None, "serve"):
        return _serve()
    if args.command == "speech":
        return asyncio.run(_speech_check())
    if args.command == "story":
        try:
            if args.action == "migrate":
                return _migrate_stories(args)
            if args.action == "import-gim":
                return asyncio.run(_import_gim(args))
            raise ValueError("不支持的剧情操作")
        except (OSError, ValueError, sqlite3.Error) as error:
            print(error, file=sys.stderr)
            return 1
    if args.command == "character":
        return asyncio.run(_draft_sheet(args))
    if args.command == "reading":
        return _draft_readings(args)
    if args.command == "greeting":
        return asyncio.run(_greeting_upload(args))
    if args.command == "backup":
        return asyncio.run(_backup(args))
    if args.command == "restore":
        return _restore(args)
    if args.command == "reembed":
        return asyncio.run(_reembed(args))
    if args.command == "eval" and args.action == "judge":
        return asyncio.run(_eval_judge(args))
    if args.command == "eval" and args.action == "memory":
        return asyncio.run(_eval_memory(args))
    if args.command == "eval":
        return asyncio.run(_eval_rerank(args))

    store = Store(args.db or database_path_from_env())
    try:
        args.run(store, args)
    except NotFound as e:
        print(e, file=sys.stderr)
        return 1
    finally:
        store.close()
    return 0


async def _speech_check() -> int:
    from eidolon.config import WindowsSpeechSettings
    from eidolon.windows_speech import WindowsSpeech, WindowsSpeechError

    try:
        configured = WindowsSpeechSettings.from_env()
        print("本机语音：" + ("windows" if configured else "未启用（仅检查组件）"))
        local = WindowsSpeech(configured or WindowsSpeechSettings())
        # Print inventory even if the selected voice/language is unavailable.
        result = await local.installed()
        for component in ("voices", "recognizers"):
            print(component + ":")
            for item in result[component]:
                print(f"  {item['name']} ({item['language']})")
        local.validate(result)
        print(f"配置有效：识别 {local.settings.recognition_language}；"
              f"合成 {local.settings.voice} ({local.settings.voice_language})，Windows 中性声音")
        return 0
    except (WindowsSpeechError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1


GRACEFUL_SHUTDOWN_SECONDS = 20
"""How long requests may finish before the server stops, within Compose's grace."""


def _serve() -> int:
    import uvicorn
    from loguru import logger

    from eidolon import server_logs
    from eidolon.app import create_app
    from eidolon.assembly import build

    # Pipecat logs through loguru, which shows everything down to DEBUG unless told
    # otherwise: what users said, and what calls send to services on their own keys.
    logger.remove()
    logger.add(sys.stderr, level="INFO")

    server_logs.configure()

    try:  # missing settings, an unusable DashScope key or Cloudflare token, a broken
        # character configuration
        settings = Settings.from_env()
        settings = asyncio.run(_find_dashscope_region(settings))
        asyncio.run(_check_judge(settings))
        backend = build(settings)
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 1
    try:  # an unfit chat model
        asyncio.run(_check_chat_llm(settings))
    except RuntimeError as e:
        asyncio.run(backend.aclose())
        print(e, file=sys.stderr)
        return 1
    app = create_app(backend)
    uvicorn.run(
        app,
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
        log_config=server_logs.uvicorn_log_config(),
        # Calls are no requests: they are hung up after, as the backend closes.
        timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_SECONDS,
    )
    return 0


async def _find_dashscope_region(settings: Settings) -> Settings:
    """The settings with the region the deployer's DashScope key works in, found by trying
    it, if Alibaba Cloud Model Studio is to hear calls on it; raises RuntimeError saying
    why, if it cannot."""
    from eidolon.bailian import BailianCheckFailed, find_region

    key = settings.stt_key
    if key is None or key.provider != "bailian":
        return settings
    try:
        region = await find_region(
            key.api_key, settings.bailian_stt_model, settings.proxy.proxy_for("stt")
        )
    except BailianCheckFailed as e:
        raise RuntimeError(f"阿里云百炼的 DASHSCOPE_API_KEY 用不了：{e}") from None
    return replace(settings, dashscope_region=region)


async def _check_judge(settings: Settings) -> None:
    """Tries Cloudflare's credentials, through the proxy or direct, as `.env` has it."""
    from eidolon.judge import JUDGE_TIMEOUT, check_judge
    from eidolon.proxy import open_client

    async with open_client(settings.proxy.proxy_for("judge"), JUDGE_TIMEOUT) as client:
        await check_judge(settings.judge, client)


async def _check_chat_llm(settings: Settings) -> None:
    """Checks the chat model on a client of its own, through the proxy or direct, as
    `.env` has it: the server's run in uvicorn's event loop, and an HTTP client cannot
    move between loops."""
    from eidolon.llm.providers import LLM_TIMEOUT, check_chat_models, open_chat_models
    from eidolon.proxy import open_client

    proxy = settings.proxy.proxy_for("chat_llm")
    models = open_chat_models(settings.chat_model, open_client(proxy, LLM_TIMEOUT))
    try:
        await check_chat_models(models, settings.chat_model)
    finally:
        await models.aclose()


def _story_target(args: argparse.Namespace, *, legacy_db: bool = False) -> Path:
    return (args.story_db or (args.db if legacy_db else None)
            or story_database_path_from_env()
            or (args.db or database_path_from_env()).with_suffix(".stories.db"))


def _checked_story_target(args: argparse.Namespace) -> Path:
    from eidolon.story_library import check_library

    path = _story_target(args, legacy_db=True)
    check_library(path)
    return path


def _active_story(args: argparse.Namespace) -> Path | None:
    from eidolon.story_library import mounted_library

    return mounted_library(_story_target(args), enabled=stories_enabled_from_env())


def _migrate_stories(args: argparse.Namespace) -> int:
    import json
    import sqlite3
    from dataclasses import asdict
    from eidolon.story_library import migrate_stories

    try:
        source = args.source or args.db or database_path_from_env()
        destination = args.output or args.story_db or story_database_path_from_env() or source.with_suffix(".stories.db")
        result = migrate_stories(source, destination)
    except (OSError, ValueError, sqlite3.Error) as error:
        print(error, file=sys.stderr)
        return 1
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    return 0


async def _import_gim(args: argparse.Namespace) -> int:
    from eidolon.characters import load_characters
    from eidolon.config import EmbeddingSettings
    from eidolon.corpus import StoryCorpus
    from eidolon.embedding import NoEmbedder, open_embedder
    from eidolon.gim_story_import import import_gim_directory

    online = None
    try:
        story_db = _story_target(args, legacy_db=True)
        protected = [args.manifest, story_db, args.db or database_path_from_env()]
        if args.index is not None:
            protected.append(args.index)
        if (args.report.resolve() in {p.resolve() for p in protected}
                or args.report.suffix.lower() != ".json"
                or args.report.resolve().is_relative_to(args.directory.resolve())):
            raise RuntimeError("报告须为 CSV 根目录之外的独立 .json 文件，不得覆盖 manifest/index/数据库")
        characters = load_characters(args.characters or characters_path_from_env())
        settings = None if args.offline else EmbeddingSettings.from_env()
        online = open_embedder(settings) if settings else None
        from eidolon.story_library import check_library
        check_library(story_db)
        corpus = StoryCorpus(story_db, online or NoEmbedder())
        try:
            report = await import_gim_directory(
                args.directory, corpus, characters.values(), manifest=args.manifest, index=args.index
            )
            report.write(args.report)
        finally:
            corpus.close()
    except (OSError, RuntimeError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    finally:
        if online is not None:
            await online.aclose()
    print(f"GIM：导入 {report.imported}，未变 {report.unchanged}，失败 {report.skipped_failures}，"
          f"待核对 outcome {report.unknown_outcomes}，待向量化 {report.pending_passages}；"
          f"报告 {args.report}")
    return 1 if report.has_errors else 0














def _draft_readings(args: argparse.Namespace) -> int:
    from eidolon.characters import load_characters
    from eidolon.readings import load_readings, readings_path
    from eidolon.world import load_world, world_path

    try:
        from eidolon.reading_draft import draft_readings, write_readings

        import pyopenjtalk  # noqa: F401
    except ImportError:
        print(
            "生成读音要用开发依赖里的 pyopenjtalk-plus：在 backend 下运行 uv sync，"
            "再用 uv run eidolon reading draft",
            file=sys.stderr,
        )
        return 1
    characters_path = args.characters or characters_path_from_env()
    path = readings_path(characters_path)
    try:
        characters = load_characters(characters_path, require_sheets=False)
        world = load_world(world_path(characters_path))
        existing = load_readings(path)
    except RuntimeError as e:  # a broken character configuration, world setting or file
        print(e, file=sys.stderr)
        return 1
    readings, report = draft_readings(existing, characters.values(), world)
    write_readings(path, readings)
    print(f"写入了 {path}，共 {len(readings)} 条")
    if report.added:
        print(f"新增 {len(report.added)} 条：{'、'.join(report.added)}")
    if report.filled:
        print(f"补上音素 {len(report.filled)} 条：{'、'.join(report.filled)}")
    if report.unread:
        print(
            f"这几位的人设开头没有「名字（せい めい）」，没有生成，请手写："
            f"{'、'.join(report.unread)}"
        )
    if world is None:
        print("没有配置 world.json 世界设定，组合名和工作人员没有生成")
    return 0


async def _greeting_upload(args: argparse.Namespace) -> int:
    from eidolon.characters import load_characters
    from eidolon.greetings import FishAudioSettings, upload_greetings
    from eidolon.readings import load_readings, readings_path
    from eidolon.s3 import S3Error, S3Settings

    characters_path = args.characters or characters_path_from_env()
    try:
        characters = load_characters(characters_path, require_sheets=False)
        readings = load_readings(readings_path(characters_path))
        bucket = S3Settings.from_env(purpose="上传招呼和开场白")
        fish = FishAudioSettings.from_env()
    except RuntimeError as e:  # a broken character configuration or readings, settings missing
        print(e, file=sys.stderr)
        return 1
    try:
        report = await upload_greetings(characters.values(), bucket, fish, readings)
    except S3Error as e:
        print(f"列不出存储桶里已有的招呼和开场白，什么都没有合成：{e}", file=sys.stderr)
        return 2
    for key in report.deleted:
        print(f"删除了旧版本 {key}")
    voiced = f"：{'、'.join(report.voiced)}" if report.voiced else ""
    print(
        f"合成并上传了 {len(report.voiced)} 句招呼和开场白{voiced}；"
        f"{report.unchanged} 句存储桶里已有，没有重新合成"
    )
    for name, why in report.failed:
        print(f"{name}：{why}", file=sys.stderr)
    if report.failed:
        print(
            f"{len(report.failed)} 处没有处理完，见上方；改好后重新运行即可，已上传的不会重复合成",
            file=sys.stderr,
        )
    return report.exit_code


async def _backup(args: argparse.Namespace) -> int:
    import sqlite3
    import time

    from eidolon.backup import EXPORT_FAILED, Backups, describe

    started = time.monotonic()
    try:
        backups = Backups(args.db or database_path_from_env(), utc_now)
        try:
            report = await backups.run(args.source)
        finally:
            backups.close()
    except sqlite3.Error as e:  # not a missing setting, which exiting 1 would say
        print(f"没有备份：备份记录写不进数据库：{e}", file=sys.stderr)
        return EXPORT_FAILED
    for wrong, line in describe(report):
        print(line, file=sys.stderr if wrong else sys.stdout)
    if report.config_error is not None or report.busy:
        return report.exit_code
    print(f"用时 {time.monotonic() - started:.0f} 秒")
    return report.exit_code


def _restore(args: argparse.Namespace) -> int:
    from eidolon.restore import NotRestored, check, restore

    database = args.db or database_path_from_env()
    try:
        if args.check:
            users = check(args.file, database)
            print(f"{args.file} 通过了检查，库里有 {users} 位用户")
            return 0
        restored = restore(args.file, database, utc_now)
    except (NotRestored, OSError) as e:  # OSError: the rename
        print(f"没有恢复，现在的数据库没有换：{e}", file=sys.stderr)
        return 1
    print(f"已用 {args.file} 替换 {database}，恢复进来的库里有 {restored.users} 位用户")
    if restored.abandoned:
        print(f"备份时正在进行的 {restored.abandoned} 条备份记录已标成没有完成")
    return 0


async def _draft_sheet(args: argparse.Namespace) -> int:
    from eidolon.characters import load_characters
    from eidolon.config import LLMSettings
    from eidolon.corpus import StoryCorpus
    from eidolon.embedding import NoEmbedder
    from eidolon.llm import LLMError
    from eidolon.llm.providers import open_llm
    from eidolon.sheet_draft import (
        DEFAULT_BUDGET,
        CannotWrite,
        NoEpisodes,
        SheetReviewed,
        check_output,
        draft_sheet,
    )

    try:
        characters = load_characters(
            args.characters or characters_path_from_env(), require_sheets=False
        )
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 1
    character = characters.get(args.character_id)
    if character is None:
        print(f"角色配置里没有 {args.character_id}（有 {'、'.join(characters)}）", file=sys.stderr)
        return 1
    target = args.output or character.sheet_path
    assert target is not None, "characters come from a configuration file"
    budget = args.budget or DEFAULT_BUDGET
    if budget < 1000:
        print("--budget 至少为 1000", file=sys.stderr)
        return 1
    try:  # before anything is spent on it
        path = check_output(target, args.force)
    except SheetReviewed as e:
        print(f"{e}，不会覆盖；确实要重新生成请加 --force", file=sys.stderr)
        return 1
    except CannotWrite as e:
        print(e, file=sys.stderr)
        return 1
    try:
        llm_settings = LLMSettings.background_from_env()
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 1

    progress = logging.StreamHandler()  # drafting takes minutes; say how far it has got
    progress.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
    logging.getLogger("eidolon.sheet_draft").addHandler(progress)
    logging.getLogger("eidolon.sheet_draft").setLevel(logging.INFO)
    llm = open_llm(llm_settings)
    corpus = StoryCorpus(_checked_story_target(args), NoEmbedder())
    try:
        report = await draft_sheet(
            character, corpus, llm, output=path, overwrite=args.force, budget=budget
        )
    except (NoEpisodes, LLMError) as e:
        print(e, file=sys.stderr)
        return 1
    finally:
        corpus.close()
        await llm.aclose()
    sampled = (
        f"（素材太多，均匀抽取了其中 {report.episodes_read} 段）"
        if report.episodes_read < report.episodes_cast
        else ""
    )
    print(
        f"已根据 {character.name} 出场的 {report.episodes_cast} 段剧情{sampled}生成人设初稿，"
        f"共请求后台模型 {report.requests} 次：{path}"
    )
    print("请人工校对，校对完成后删除文件第一行的草稿标记。")
    return 0


async def _reembed(args: argparse.Namespace) -> int:
    from eidolon.characters import load_characters
    from eidolon.config import EmbeddingSettings
    from eidolon.embedding import EmbeddingError, open_embedder
    from eidolon.reembed import reembed
    from eidolon.world import load_world, world_path

    try:
        characters_path = args.characters or characters_path_from_env()
        characters = load_characters(characters_path)
        world = load_world(world_path(characters_path))
        settings = EmbeddingSettings.required_from_env()
        library = _active_story(args)
    except (RuntimeError, ValueError, sqlite3.Error) as e:
        print(e, file=sys.stderr)
        return 1

    progress = logging.StreamHandler()  # a whole corpus takes a while
    progress.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
    logging.getLogger("eidolon.reembed").addHandler(progress)
    logging.getLogger("eidolon.reembed").setLevel(logging.INFO)
    embedder = open_embedder(settings)
    try:
        report = await reembed(
            args.db or database_path_from_env(), characters.values(), embedder, world=world, story_path=library
        )
    except EmbeddingError as e:
        print(
            f"重新向量化中断（已完成的部分会保留，旧向量没有删除，重新运行即可继续）：{e}",
            file=sys.stderr,
        )
        return 1
    finally:
        await embedder.aclose()
    print(f"向量化模型：{embedder.model}")
    for each in report.embedded:
        print(f"{each.label}：新向量化 {each.count} {each.unit}")
    print(f"删除了其他模型的 {report.forgotten} 个向量")
    return 0


async def _eval_rerank(args: argparse.Namespace) -> int:
    from dataclasses import replace

    from eidolon.characters import load_characters
    from eidolon.config import EmbeddingSettings, RerankSettings
    from eidolon.embedding import EmbeddingError, open_embedder
    from eidolon.rerank import RerankError, SiliconFlowReranker, thresholds_for
    from eidolon.rerank_eval import CalibrationError, evaluate, load_calibration, report
    from eidolon.retrieval import open_reference_sources
    from eidolon.world import load_world, world_path

    try:
        characters_path = args.characters or characters_path_from_env()
        characters = load_characters(characters_path)
        world = load_world(world_path(characters_path))
        calibration = load_calibration(args.file, world)
        embedding = EmbeddingSettings.required_from_env()
        library = _active_story(args)
        rerank = RerankSettings.from_env()
        if rerank is None:
            raise RuntimeError("环境变量 SILICONFLOW_API_KEY 未设置（重排需要）")
    except (RuntimeError, ValueError, sqlite3.Error) as e:
        print(e, file=sys.stderr)
        return 1
    if args.model:
        rerank = replace(rerank, model=args.model)
    warnings = logging.StreamHandler()  # missing vectors skew the calibration
    warnings.setFormatter(logging.Formatter("注意：%(message)s"))
    logging.getLogger("eidolon.retrieval").addHandler(warnings)
    embedder = open_embedder(embedding)
    reranker = SiliconFlowReranker(rerank.api_key, rerank.model, rerank.base_url)
    sources = open_reference_sources(
        args.db or database_path_from_env(), embedder, characters.values(), world, story_path=library
    )
    try:
        results = await evaluate(calibration, characters, reranker, sources)
    except (CalibrationError, EmbeddingError, RerankError) as e:
        print(e, file=sys.stderr)
        return 1
    finally:
        sources.close()
        await embedder.aclose()
        await reranker.aclose()
    print(report(results, rerank.model, thresholds_for(rerank)))
    return 0


async def _eval_judge(args: argparse.Namespace) -> int:
    import json

    from eidolon.characters import load_characters
    from eidolon.config import (
        CLOUDFLARE_JUDGE_MODELS,
        CloudflareJudgeSettings,
        EmotionSettings,
        judge_from_env,
    )
    from eidolon.judge import judge_thresholds, open_judge, warn_if_uncalibrated
    from eidolon.judge_eval import (
        JudgeEvalError,
        evaluate,
        load_judge_eval,
        only,
        report,
        summarize,
    )

    try:
        characters = load_characters(args.characters or characters_path_from_env())
        judge_eval = load_judge_eval(args.file, characters)
        if args.only:
            judge_eval = only(judge_eval, args.only)
        emotion = EmotionSettings.from_env()
        judge = judge_from_env(args.provider)
        if judge is None:
            raise RuntimeError("环境变量 JEV_API_KEY 未设置（判断模型需要）")
        if args.model:
            if isinstance(judge, CloudflareJudgeSettings) and args.model not in CLOUDFLARE_JUDGE_MODELS:
                raise RuntimeError(
                    f"Cloudflare 的判断模型只能是 {'、'.join(CLOUDFLARE_JUDGE_MODELS)}，而不是 {args.model}"
                )
            judge = replace(judge, model=args.model)
    except (RuntimeError, JudgeEvalError) as e:
        print(e, file=sys.stderr)
        return 1
    warnings = logging.StreamHandler()  # a model without thresholds of its own
    warnings.setFormatter(logging.Formatter("注意：%(message)s"))
    logging.getLogger("eidolon.judge").addHandler(warnings)
    warn_if_uncalibrated(judge.model)
    thresholds = judge_thresholds(judge, emotion)
    model = open_judge(judge)
    try:
        results = await evaluate(judge_eval, characters, model, thresholds)
    finally:
        await model.aclose()
    summary = summarize(results, judge.model, thresholds)
    print(report(results, summary))
    if args.json:
        args.json.write_text(
            json.dumps(results.to_json(summary), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"\n结果已写入 {args.json}")
    return 0


async def _eval_memory(args: argparse.Namespace) -> int:
    import json
    import tempfile

    from eidolon.characters import load_characters
    from eidolon.config import EmbeddingSettings, LLMSettings, RerankSettings, judge_from_env
    from eidolon.embedding import open_embedder
    from eidolon.judge import judge_thresholds_for, open_judge, warn_if_uncalibrated
    from eidolon.llm.providers import open_llm
    from eidolon.memory_eval import (
        MemoryEvalError,
        MemoryServices,
        evaluate,
        load_memory_eval,
        report,
        summarize,
    )
    from eidolon.rerank import SiliconFlowReranker, thresholds_for

    try:
        characters = load_characters(args.characters or characters_path_from_env())
        memory_eval = load_memory_eval(args.file, characters)
    except (RuntimeError, MemoryEvalError) as e:
        print(e, file=sys.stderr)
        return 1
    try:
        background = LLMSettings.background_from_env()
        embedding = EmbeddingSettings.required_from_env()
        rerank = RerankSettings.from_env()
        if rerank is None:
            raise RuntimeError("环境变量 SILICONFLOW_API_KEY 未设置（重排需要）")
        judge = judge_from_env()
        if judge is None:
            raise RuntimeError("环境变量 JEV_API_KEY 未设置（判断模型需要）")
    except RuntimeError as e:
        print(f"记忆评测要用部署者配置的背景模型、向量化、重排和判断模型：{e}", file=sys.stderr)
        return 1
    warnings = logging.StreamHandler()  # a model without thresholds of its own
    warnings.setFormatter(logging.Formatter("注意：%(message)s"))
    logging.getLogger("eidolon.judge").addHandler(warnings)
    warn_if_uncalibrated(judge.model)
    llm = open_llm(background)
    embedder = open_embedder(embedding)
    reranker = SiliconFlowReranker(rerank.api_key, rerank.model, rerank.base_url)
    judge_model = open_judge(judge)
    services = MemoryServices(
        background_llm=llm,
        embedder=embedder,
        reranker=reranker,
        rerank_thresholds=thresholds_for(rerank),
        judge_model=judge_model,
        judge_thresholds=judge_thresholds_for(judge.model),
    )
    models = {
        "background": background.model, "judge": judge.model, "embedding": embedding.model,
        "rerank": rerank.model,
    }
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as workdir:
            results = await evaluate(
                memory_eval, characters, services, Path(workdir),
                lambda case: print(case, file=sys.stderr, flush=True),
            )
    except MemoryEvalError as e:
        print(e, file=sys.stderr)
        return 1
    finally:
        await llm.aclose()
        await embedder.aclose()
        await reranker.aclose()
        await judge_model.aclose()
    summary = summarize(results, models)
    print(report(results, summary))
    if args.json:
        args.json.write_text(
            json.dumps(results.to_json(summary), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"\n结果已写入 {args.json}")
    return 0


def _list_users(store: Store, _: argparse.Namespace) -> None:
    for user in store.list_users():
        methods = "、".join(
            f"{PROVIDER_LABELS.get(m.provider, m.provider)} {m.display_name}"  # pyright: ignore[reportCallIssue, reportArgumentType]
            f" ({m.provider}:{m.subject})"
            for m in store.sign_in_methods(user.id)
        ) or "（没有登录方式）"
        state = f"已封禁于 {user.banned_at}" if user.banned_at else "正常"
        if user.ban_note:
            state += f"（备注：{user.ban_note}）"
        print(f"{user.id}\t{user.name}\t{methods}\t创建于 {user.created_at}\t{state}")


def _ban_user(store: Store, args: argparse.Namespace) -> None:
    store.set_banned(args.user_id, datetime.now(UTC), args.note or None)
    print(f"已封禁用户 {args.user_id}，并让他在所有设备上退出登录；正在进行的通话会在几秒内挂断")


def _unban_user(store: Store, args: argparse.Namespace) -> None:
    store.set_banned(args.user_id, None)
    print(f"已解封用户 {args.user_id}")


def _user_usage(store: Store, args: argparse.Namespace) -> None:
    store.get_user(args.user_id)  # NotFound for no such user
    # The limits play no part in looking over what was used.
    usage = UsageLimiter(args.db or database_path_from_env(), UsageLimits(), utc_now)
    try:
        day = usage.last_day(args.user_id)
    finally:
        usage.close()
    print(f"用户 {args.user_id} 最近 24 小时的用量（UTC，按小时）：")
    print("时间\t文字回合\t通话\t其中不计入限额的回合\t其中不计入限额的通话")
    for hour, tally in day.hours.items():
        print(f"{hour:%Y-%m-%d %H:00}\t{_tally_columns(tally)}")
    print(f"合计\t{_tally_columns(day.total)}")


def _tally_columns(tally: Tally) -> str:
    return f"{tally.turns}\t{tally.calls}\t{tally.exempt_turns}\t{tally.exempt_calls}"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="eidolon", description="Eidolon-GIM 后端")
    parser.add_argument(
        "--db", type=Path, help="数据库文件（默认取环境变量 EIDOLON_DATABASE_PATH）"
    )
    commands = parser.add_subparsers(dest="command", metavar="命令")
    parser.add_argument("--story-db", type=Path, help="独立剧情库；默认 EIDOLON_STORY_DATABASE_PATH 或应用库同目录的 *.stories.db")
    commands.add_parser("serve", help="启动服务（默认）")
    speech = commands.add_parser("speech", help="检查 Windows 本机中性语音").add_subparsers(
        dest="action", required=True
    )
    speech.add_parser("check", help="列出安装的声音/识别器，验证本机配置（不读取密钥）")

    user = commands.add_parser("user", help="管理用户").add_subparsers(
        dest="action", required=True, metavar="操作"
    )
    user.add_parser(
        "list", help="列出所有用户：ID、名字、登录方式（括号里是填进 EIDOLON_ADMINS 的标识）、创建时间、是否已封禁"
    ).set_defaults(run=_list_users)
    ban = user.add_parser("ban", help="封禁用户，并让他在所有设备上退出登录")
    ban.add_argument("user_id", help="用户 ID（见 user list）")
    ban.add_argument("--note", help="封禁的原因，只有管理者看得到（user list 和后台里显示）")
    ban.set_defaults(run=_ban_user)
    unban = user.add_parser("unban", help="解除封禁")
    unban.add_argument("user_id", help="用户 ID（见 user list）")
    unban.set_defaults(run=_unban_user)
    usage = user.add_parser(
        "usage",
        help="查看用户最近 24 小时按小时统计的用量（最近 7 天、30 天的用量在后台的用户详情里看）",
    )
    usage.add_argument("user_id", help="用户 ID（见 user list）")
    usage.set_defaults(run=_user_usage)

    story = commands.add_parser("story", help="管理剧情库").add_subparsers(
        dest="action", required=True, metavar="操作"
    )
    migrate = story.add_parser("migrate", help="备份旧应用库，并无损导出独立剧情库；不删除原数据")
    migrate.add_argument("--source", type=Path, help="旧应用数据库，默认全局 --db 或 EIDOLON_DATABASE_PATH")
    migrate.add_argument("--output", type=Path, help="新剧情库，默认全局 --story-db 或 *.stories.db")
    import_gim = story.add_parser("import-gim", help="导入本机学园 CSV")
    import_gim.add_argument("directory", type=Path, help="CSV 根目录；index 中路径相对此目录")
    import_gim.add_argument("--index", type=Path, help="可选 adv_*.txt → CSV 路径 JSON")
    import_gim.add_argument("--manifest", type=Path, required=True, help="来源、版本、使用条件和 outcome JSON")
    import_gim.add_argument("--report", type=Path, required=True, help="CSV 根目录之外的审计报告 .json")
    import_gim.add_argument("--offline", action="store_true", help="只存文本和目录，之后用 reembed 向量化")
    import_gim.add_argument("--characters", type=Path, help="角色配置文件；默认 EIDOLON_CHARACTERS_PATH")

    character = commands.add_parser("character", help="管理角色").add_subparsers(
        dest="action", required=True, metavar="操作"
    )
    draft = character.add_parser(
        "draft-sheet", help="用后台模型根据角色出场的剧情生成人设初稿，写入人设文件"
    )
    draft.add_argument("character_id", help="角色标识，例如 temari")
    draft.add_argument(
        "--characters",
        type=Path,
        help="角色配置文件（默认取环境变量 EIDOLON_CHARACTERS_PATH）",
    )
    draft.add_argument(
        "--output",
        type=Path,
        help="写到这个文件，而不是角色配置里的人设文件（例如在人设目录只读的容器里）",
    )
    draft.add_argument("--force", action="store_true", help="覆盖已经校对过的人设")
    draft.add_argument(
        "--budget",
        type=int,
        help="每次请求后台模型最多带多少字的剧情素材（默认 40000，至少 1000），超出时分批总结",
    )

    reading = commands.add_parser("reading", help="管理读音").add_subparsers(
        dest="action", required=True, metavar="操作"
    )
    reading_draft = reading.add_parser(
        "draft",
        help="从人设开头的「名字（せい めい）」和世界设定生成角色配置旁边的读音文件 readings.toml 的初稿；"
        "已有文件时只给音素为空的条目补上音素、补进文件里还没有的角色和组合，已有音素的条目不动"
        "（要用开发依赖：uv run eidolon reading draft）",
    )
    reading_draft.add_argument(
        "--characters",
        type=Path,
        help="角色配置文件（默认取环境变量 EIDOLON_CHARACTERS_PATH）",
    )

    greeting = commands.add_parser("greeting", help="管理落地页的招呼和开场白").add_subparsers(
        dest="action", required=True, metavar="操作"
    )
    greeting_upload = greeting.add_parser(
        "upload",
        help="用每位角色的音色和部署者的语音合成 key（FISH_AUDIO_API_KEY、FISH_AUDIO_MODEL）把角色配置里的招呼和开场白合成为 mp3，"
        "上传到立绘的存储桶（EIDOLON_STAND_S3_*）的 greetings/、call-openers/ 下，并删掉旧版本和配置里已经没有的；"
        "只合成存储桶里还没有的（可重复执行；存储桶列不出来时退出码为 2，有没上传完的时为 3）",
    )
    greeting_upload.add_argument(
        "--characters",
        type=Path,
        help="角色配置文件（默认取环境变量 EIDOLON_CHARACTERS_PATH）",
    )

    evaluation = commands.add_parser("eval", help="评估检索和判断效果").add_subparsers(
        dest="action", required=True, metavar="操作"
    )
    rerank = evaluation.add_parser(
        "rerank",
        help="用校准数据集对着本地的剧情库打印重排分数分布，用来定重排阈值",
    )
    rerank.add_argument(
        "--model", help="重排模型（默认取环境变量 RERANK_MODEL），例如 Qwen/Qwen3-Reranker-0.6B"
    )
    rerank.add_argument(
        "--file",
        type=Path,
        default=Path("eval/rerank-calibration.toml"),
        help="校准数据集（默认 eval/rerank-calibration.toml）",
    )
    rerank.add_argument(
        "--characters",
        type=Path,
        help="角色配置文件（默认取环境变量 EIDOLON_CHARACTERS_PATH）",
    )

    judge = evaluation.add_parser(
        "judge",
        help="用判断模型的 eval 集逐条问判断模型，打印准确率和概率分布，用来定阈值、比较各家模型",
    )
    judge.add_argument(
        "--provider",
        choices=JUDGE_PROVIDERS,
        help="判断模型的服务商（默认取环境变量 JUDGE_PROVIDER），方便同一份配置轮流跑",
    )
    judge.add_argument(
        "--model",
        help="判断模型（默认取环境变量 JEV_MODEL 或 CLOUDFLARE_JUDGE_MODEL），"
        "例如 typesafe/jev-1.13、clef、clef-flash",
    )
    judge.add_argument(
        "--file",
        type=Path,
        default=Path("eval/judge.toml"),
        help="判断模型的 eval 集（默认 eval/judge.toml）",
    )
    judge.add_argument(
        "--only",
        choices=["retrieval", "emotion", "affinity", "photo"],
        action="append",
        help="只跑这一类用例（可以写几次，默认全跑），例如 --only photo",
    )
    judge.add_argument(
        "--characters",
        type=Path,
        help="角色配置文件（默认取环境变量 EIDOLON_CHARACTERS_PATH）",
    )
    judge.add_argument("--json", type=Path, help="把逐条结果和汇总写成 JSON 文件，方便对比")

    memory = evaluation.add_parser(
        "memory",
        help="用记忆评测集按真实回合的路径跑提炼和召回，按题型打印通过数，用来和提交的基线比较"
        "（用部署者配置的背景模型、向量化、重排和判断模型，记忆写在临时数据库里）",
    )
    memory.add_argument(
        "--file",
        type=Path,
        default=Path("eval/memory.toml"),
        help="记忆评测集（默认 eval/memory.toml）",
    )
    memory.add_argument(
        "--characters",
        type=Path,
        help="角色配置文件（默认取环境变量 EIDOLON_CHARACTERS_PATH）",
    )
    memory.add_argument(
        "--json", type=Path, help="把逐条结果和汇总写成 JSON 文件（基线就是这样提交的）"
    )

    backup = commands.add_parser(
        "backup",
        help="把数据库压缩、用 age 公钥加密后备份到私有的存储桶，并删掉过了保留期（默认 30 天）的备份，"
        "最新的一份总是保留（存储桶、公钥和保留期取环境变量 EIDOLON_BACKUP_*；"
        "导出失败退出码为 2，上传失败为 3，删除过期备份失败为 4，上一次备份还没结束为 6）",
    )
    backup.add_argument(
        "--source",
        choices=["manual", "cron"],
        default="manual",
        help="谁发起的这次备份，记进备份记录、显示在看板上（默认 manual；主机上的 cron 传 cron）",
    )

    restore = commands.add_parser(
        "restore",
        help="用在自己电脑上解密好的备份（.db 或 .db.gz）替换数据库，要先停后端"
        "（服务器上用 deploy/db-restore.sh）；文件损坏、不是 SQLite 或者不是本项目的数据库时什么都不动，"
        "退出码为 1",
    )
    restore.add_argument("file", type=Path, help="解密后的备份文件，压缩的和解压后的都行")
    restore.add_argument(
        "--check",
        action="store_true",
        help="只检查文件、报出用户数，不替换（不用停后端；deploy/db-restore.sh 先这样检查一遍）",
    )

    reembed = commands.add_parser(
        "reembed",
        help="换了向量化服务、模型或维度后，用库里的原文重新向量化剧情库、角色资料、歌曲唱片和演出、记忆"
        "（可中断、可重复执行；服务不必停止）",
    )
    reembed.add_argument(
        "--characters",
        type=Path,
        help="角色配置文件（默认取环境变量 EIDOLON_CHARACTERS_PATH）",
    )
    return parser


if __name__ == "__main__":
    sys.exit(main())
