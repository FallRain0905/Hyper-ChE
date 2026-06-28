# -*- coding: utf-8 -*-
import sys
import io
import re
import logging  # Import logging early for SafeLogFilter class definition
import traceback
import hashlib
import contextvars
from logging.handlers import RotatingFileHandler

# Safe string conversion function for Windows encoding
def safe_str(obj):
    """Convert object to string with safe encoding for Windows gbk"""
    try:
        # First try to convert to string
        s = str(obj)

        if sys.platform == 'win32':
            # Use a more comprehensive approach to handle all problematic Unicode characters
            safe_chars = []
            for char in s:
                try:
                    # Test if the character can be encoded in gbk
                    char.encode('gbk')
                    safe_chars.append(char)
                except (UnicodeEncodeError, UnicodeDecodeError):
                    # If it fails, replace with a safe representation
                    safe_chars.append(f'[U+{ord(char):04X}]')

            s = ''.join(safe_chars)

        return s
    except Exception as e:
        # If conversion fails completely, return a generic error message
        return f"[ENCODING ERROR: {type(e).__name__}]"

# Safe print function for Windows encoding
def safe_print(*args, **kwargs):
    """Print function that handles Unicode encoding issues safely"""
    try:
        # Convert all arguments to safe strings
        safe_args = [safe_str(arg) for arg in args]
        print(*safe_args, **kwargs)
    except Exception as e:
        # If printing fails, try a basic fallback
        try:
            print(f"[PRINT ERROR: {safe_str(e)}]")
        except Exception:
            # Ultimate fallback
            print("[UNABLE TO PRINT MESSAGE DUE TO ENCODING ERROR]")

def redact_text_for_log(text: str) -> str:
    """Mask common API key/token patterns in free-form log strings."""
    try:
        text = re.sub(r"sk-[A-Za-z0-9_\-]{8,}", "sk-[REDACTED]", text)
        text = re.sub(
            r"(?i)(api[_-]?key|apikey|embeddingApiKey|authorization|token|secret)(\s*[:=]\s*)(['\"]?)[^,'\"\s}]+",
            r"\1\2\3[REDACTED]",
            text,
        )
    except Exception:
        pass
    return text

# Safe log filter for Windows encoding
class SafeLogFilter(logging.Filter):
    """Log filter that handles Unicode encoding issues"""

    def filter(self, record):
        try:
            # Safe-ify the fully formatted log message and remove args to avoid double interpolation.
            try:
                message = record.getMessage()
            except Exception:
                message = str(record.msg)
            record.msg = redact_text_for_log(safe_str(message))
            record.args = ()
        except Exception:
            # If filtering fails, at least don't break the logging
            pass
        return True

def extract_user_friendly_error(error_message: str) -> str:
    """Extract a concise user-facing error message from provider errors."""
    error_lower = str(error_message or "").lower()
    if "insufficient" in error_lower or "balance" in error_lower:
        return "API account balance is insufficient. Please recharge or switch to another available key."
    if "permissiondenied" in error_lower or "permission denied" in error_lower or "403" in error_lower:
        return "API permission denied. Please check account quota, model access, and API key."
    if "401" in error_lower or "unauthorized" in error_lower:
        return "API key is invalid or unauthorized."
    if "rate" in error_lower or "limit" in error_lower or "429" in error_lower:
        return "API rate limit reached. Please wait or reduce concurrency."
    if "timeout" in error_lower:
        return "Request timed out. Please check the provider or reduce document size/concurrency."
    if "quota" in error_lower:
        return "API quota has been exhausted."
    if "invalid_request" in error_lower or "badrequest" in error_lower or "400" in error_lower:
        return "Invalid API request. Please check model name, base URL, and request format."
    if "connection" in error_lower:
        return "Network connection error. Please check network or provider availability."
    return f"Processing failed: {str(error_message)[:160]}"


def extract_detailed_exception_message(error: Exception) -> str:
    """Extract the underlying exception message from RetryError/OpenAI wrappers."""
    messages = [safe_str(error)]

    try:
        last_attempt = getattr(error, "last_attempt", None)
        inner_error = last_attempt.exception() if last_attempt else None
        if inner_error is not None:
            messages.append(f"{type(inner_error).__name__}: {safe_str(inner_error)}")
            body = getattr(inner_error, "body", None)
            if body:
                messages.append(f"body={safe_str(body)}")
            status_code = getattr(inner_error, "status_code", None)
            if status_code:
                messages.append(f"status_code={status_code}")
            code = getattr(inner_error, "code", None)
            if code:
                messages.append(f"code={code}")
    except Exception:
        pass

    for chain_attr in ("__cause__", "__context__"):
        try:
            chained = getattr(error, chain_attr, None)
            if chained is not None:
                messages.append(f"{chain_attr}={type(chained).__name__}: {safe_str(chained)}")
                body = getattr(chained, "body", None)
                if body:
                    messages.append(f"{chain_attr}.body={safe_str(body)}")
                status_code = getattr(chained, "status_code", None)
                if status_code:
                    messages.append(f"{chain_attr}.status_code={status_code}")
                code = getattr(chained, "code", None)
                if code:
                    messages.append(f"{chain_attr}.code={code}")
        except Exception:
            pass

    return redact_text_for_log(" | ".join(dict.fromkeys(messages)))

SENSITIVE_LOG_KEYS = {
    "api_key",
    "apikey",
    "apiKey",
    "embeddingApiKey",
    "embedding_api_key",
    "authorization",
    "token",
    "secret",
}

def redact_for_log(value):
    """Docstring."""
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            if key in SENSITIVE_LOG_KEYS or any(s in key.lower() for s in ("key", "token", "secret", "authorization")):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = redact_for_log(item)
        return redacted
    if isinstance(value, list):
        return [redact_for_log(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_for_log(item) for item in value)
    if isinstance(value, str):
        return redact_text_for_log(value)
    return value

def log_detailed_exception(logger: logging.Logger, title: str, error: Exception, context=None) -> str:
    """Log an exception with context and traceback."""
    detailed_error = extract_detailed_exception_message(error)
    logger.error(f"{title}: {detailed_error}")

    if context:
        try:
            logger.error(
                f"{title} context: "
                f"{json.dumps(redact_for_log(context), ensure_ascii=False, default=safe_str)}"
            )
        except Exception:
            logger.error(f"{title} context: {safe_str(redact_for_log(context))}")

    try:
        logger.error(
            f"{title} traceback:\n"
            f"{''.join(traceback.format_exception(type(error), error, error.__traceback__))}"
        )
    except Exception:
        logger.error(f"{title} traceback: <failed to format traceback>")

    return detailed_error

# Fix Windows encoding issue (only if not running under uvicorn)
# Check if we're running under uvicorn to avoid conflicts with its logging system
if sys.platform == 'win32' and 'uvicorn' not in sys.modules:
    try:
        # Only wrap if they're not already wrapped
        if not isinstance(sys.stdout, io.TextIOWrapper):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        if not isinstance(sys.stderr, io.TextIOWrapper):
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception as e:
        # If wrapping fails, continue without it - better to have encoding issues than crash
        pass

from fastapi import FastAPI, UploadFile, File, HTTPException, WebSocket, WebSocketDisconnect, Form, Request, Response, Depends
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from auth import AUTH_COOKIE_NAME, auth_store, create_token
from db import get_hypergraph, getFrequentVertices, get_vertices, get_hyperedges, get_vertice, get_vertice_neighbor, get_hyperedge_neighbor_server, add_vertex, add_hyperedge, delete_vertex, delete_hyperedge, update_vertex, update_hyperedge, get_hyperedge_detail, db_manager, get_theme_hypergraph, get_theme_vertices, get_theme_hyperedges, get_theme_vertex_neighbor
from file_manager import file_manager
from kb_manager import KnowledgeBaseManager
import json
import os
import gc
import time
import asyncio
import numpy as np
import importlib.util
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional, Any, Dict
from io import StringIO
from datetime import datetime

# 濠电姷鏁告慨鐑藉极閹间礁纾块柟瀵稿Х缁€濠囨煃瑜滈崜姘跺Φ閸曨垰鍗抽柛鈩冾殔椤忣亪鏌?HyperRAG 闂傚倸鍊搁崐鐑芥嚄閸洖纾块柣銏㈩焾閻ょ偓绻濋棃娑卞剬闁逞屽墾缁犳挸鐣锋總绋课ㄩ柕澹懎骞€闂佽崵鍠愮划宀€鎹㈠鈧畷娲焵椤掍降浜滈柟鐑樺灥閳ь剙缍婂鎶藉煛閸涱喚鍘卞┑鈽嗗灣婵潙煤閵堝鍎?
# 闂傚倸鍊搁崐椋庣矆娓氣偓瀹曘儳鈧綆鍠楅崕鎴犳喐閻楀牆绗掔痪鎯ф健濮婃椽顢楅埀顒傜矓閻㈢纾跨€广儱娲ㄧ壕钘壝归敐鍫殐闁绘帊绮欓弻宥囩磼濡儵鎷婚梺閫炲苯澧紒鐘茬Ч瀹曟洟鏌嗗鍛枃闁硅壈鎻徊鐐垔婵傚憡鐓涢悘鐐额嚙閸旀粓鏌涙繝鍕毈闁哄矉缍佹慨鈧柕鍫濇闁款參鏌ｉ姀鈺佺仩闁绘牕銈稿璇测槈濡攱鐎婚棅顐㈡处濡繐螞閿曞倹鈷戦弶鐐村椤︼妇绱掓径搴＄厫缂佸倹甯￠弫鍐磼濞戞妾┑鐘灱濞夋稒绺介弮鍫濈闁绘垼濮ら埛鎺懨归敐鍛暈闁哥喓鍋熼惀顏堝级鐠恒剱褏鈧娲滈幊鎾绘偩閻戣棄鐐婇柍鍝勫暟閺嗐儵姊绘担渚劸闁活剙銈稿畷鎴︽倷閻戞ê鈧灝鈹戦悩宕囶暡闁绘挻鐟╁娲敇閵娧呮殸濠电偛鎳庣粔褰掑蓟閿濆應妲堟繛鍡樺姇绾炬娊姊洪崫鍕効缂佽鲸娲樼粋鎺楁晜閻愵剙鐝伴梺鍦帛鐢帡锝炲顑芥斀闁绘﹩鍠栭悘杈ㄣ亜椤愩埄妯€闁轰礁鍟存慨鈧柣妯虹仛濞堥箖姊洪棃娑辨Ф闁稿骸顭烽幊?hyperrag 闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁撻悩鍐蹭罕闂佸搫娲㈤崹鍦不閻樼粯鐓欓梺顓ㄧ畱閸樻挳鏌＄€ｎ偅顥堥柡宀€鍠愬蹇斻偅閸愨晩鈧秹姊虹粙鍧楊€楁繛鎾棑濡叉劙骞橀幇浣告倯闂佸憡渚楅崹宥堫樄闁哄备鍓濋幏鍛村传閵夋劑鍊曢湁闁绘瑥鎳愰悾鐢碘偓瑙勬礃閸旀瑩骞冮姀鈽嗘Ч閹肩话銈庡敼闂傚倸鍊搁崐鐑芥嚄閸洏鈧焦绻濋崒妤佺亙濠电偞鍨剁划宀劼烽崒鐐粹拻濞撴埃鍋撻柍褜鍓涢崑娑㈡嚐椤栨稒娅犳い鏍ㄧ矌绾惧吋銇勯弮鍥т汗闁绘帒鎽滈埀顒冾潐濞测晝寰婃ィ鍐ㄎч柨婵嗩槸缁€鍐煃鏉炵増顦烽柛鎴滅矙濮婄粯鎷呴崨濠傛殘闂佺懓鎽滈崗姗€骞冮悙鐑樻櫆闁告挆鍛婵犲痉鏉库偓鏇㈠疮椤栫偛绐楅柟鎵閻撶喐淇婇妶鍌氫壕闂佺粯顨呴敃锔界珶閺囥垺鍋ㄩ柛娑橈功閸樻捇鎮峰鍕煉鐎规洘绮岄～婵囨綇閵娿儱绨ラ梻浣侯焾閺堫剛绮欓幒妤€鐭楅煫鍥ㄧ⊕閻撶喖鏌熼柇锕€澧柟顖氱墢缁辨帡鍩€?sys.path
if importlib.util.find_spec("hyperrag") is None:
    for parent in Path(__file__).resolve().parents:
        if (parent / "hyperrag" / "__init__.py").exists():
            sys.path.insert(0, str(parent))  # 濠电姷鏁告慨鐑藉极閹间礁纾绘繛鎴旀嚍閸ヮ剦鏁囬柕蹇曞Х椤︻噣鎮楅獮鍨姎妞わ富鍨崇划鍫ュ醇濠㈡繂缍婂畷妤呭礂閼测晝鈻忛梻浣告啞閻熴儵鏁冮鍫濊摕婵炴垯鍨归悡娑㈡煕鐏炶鈧牠鎮挎笟鈧铏规嫚閳ュ磭浠╅柣搴㈠嚬閸犳艾危閹扮増鍊风€瑰壊鍠栭幃鎴炵節閵忥絾纭炬い鎴濇閳诲秹寮介鐔哄幗闂婎偄娲﹀ú鏍ㄧ閳哄懏鐓曢悗锝庡亜婵秹鏌熼鐓庢Щ闁宠鍨归埀顒婄秵閸嬪棝宕?闂?hyperrag
            break

try:
    from hyperrag import HyperRAG, QueryParam
    from hyperrag.utils import EmbeddingFunc
    from hyperrag.llm import openai_embedding, openai_complete_if_cache, openai_complete_stream_if_cache
    HYPERRAG_AVAILABLE = True
except ImportError as e:
    print(f"HyperRAG not available: {e}")
    HYPERRAG_AVAILABLE = False

# 濠电姷鏁告慨鐑藉极閹间礁纾块柟瀵稿Х缁€濠囨煃瑜滈崜姘跺Φ閸曨垰鍗抽柛鈩冾殔椤忣亪鏌涘▎蹇曠缂佺粯绻勯崰濠冨緞瀹€濠傛暪g-RAG闂傚倸鍊峰ù鍥敋瑜嶉湁闁绘垼妫勯弸渚€鏌熼梻瀵割槮闁稿被鍔庨幉鎼佸棘鐠恒劍娈?
# 闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁嶉崟顐ｇ€抽悗骞垮劚椤︻垶宕归崒婧惧亾鐟欏嫭绀€婵炲眰鍔庣划濠氬籍閸喓鍘遍悗鍏夊亾闁逞屽墴瀹曟垵鈽夐姀鈥崇彅闂佺粯鏌ㄩ崥瀣偂韫囨搩鐔嗛柤鍝ユ暩閵嗘帡鏌ｉ敐鍫ュ摵闁靛洤瀚版俊鐑芥晜閸撗冾槱yper-RAG闂傚倸鍊搁崐椋庣矆娓氣偓楠炴牠顢曢妶鍥╃厠闂佸搫顦伴崺濠囨嚀閸ф鐓曟俊銈呭暕缁辫櫕绻涘顔荤盎缂佺媭鍨堕幃姗€鎮欐０婵嗘暯濠殿喛顫夐〃濠傤潖濞差亜浼犻柛鏇ㄥ墮缁愭盯姊虹粙娆惧剳濠殿喚鍏橀崺鈧い鎺嶈兌椤ｆ煡鏌ｉ悤鍌氼洭闁瑰箍鍨归埥澶愬閳╁啯鐝抽梻浣稿閸嬫帡宕戦崟顐熸灁妞ゆ挾鍠撶弧鈧┑鐐茬墕閻忔繈寮搁妶澶嬬厱閻庯絻鍔岄埀顒佹礋閹儳鐣￠柇锔藉兊闂佸吋鎮傚褔宕滈鐔虹瘈缁剧増锚婢ф煡鎮?path闂傚倸鍊搁崐鐑芥倿閿旈敮鍋撶粭娑樻噽閻瑩鏌熺€电浠ч梻鍕閺岋繝宕橀敐鍛缂傚倷鑳剁划顖炴儎椤栨氨鏆﹂柤纰卞墮缁躲倖銇?rag/cograg闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁撻悩鍐蹭画闂侀潧鐗嗗ú鈺傛叏閸愯褰掓偂鎼达絾鎲奸梺绋款儑婵敻骞堥妸銉庣喖骞愭惔锝冣偓鎰磽娴ｆ彃浜?
if importlib.util.find_spec("cograg") is None:
    for parent in Path(__file__).resolve().parents:
        # 濠电姷鏁告慨鐑姐€傞挊澹╋綁宕ㄩ弶鎴狅紱闂侀€炲苯澧撮柡灞剧〒閳ь剨缍嗛崑鍛暦瀹€鍕厸鐎光偓鐎ｎ剛锛熸繛瀵稿婵″洭骞忛悩璇茬闁圭儤鍩堝銉モ攽閻樻鏆柍褜鍓欓崯璺ㄧ棯瑜旈弻鐔碱敊閻撳簶鍋撻幖浣瑰仼闁绘垼妫勫敮闂佸啿鎼崐鐟扳枍閸℃稒鈷戦柛蹇涙？閼割亪鏌涙惔銏㈡创闁靛棗鍟撮幃楣冨箮閻氱垘-RAG闂傚倸鍊搁崐椋庣矆娓氣偓楠炴牠顢曢妶鍥╃厠闂佸搫顦伴崺濠囨嚀閸ф鐓曟俊銈呭暕缁辫櫕绻涘顔荤盎缂佺媭鍨堕幃姗€鎮欐０婵嗘暯濠殿喛顫夐〃濠傤潖濞差亜浼犻柛鏇ㄥ墰閵堚晜绻涚€涙鐭岄柛瀣枔閸掓帡宕奸妷銉ь槹濡炪倖鐗楃粙鎾诲储闁秵鈷戦柛婵嗗閻т線鏌涢弴銊ヤ簼妞ゅ繒濞€濮婄粯鎷呯粵瀣異闂佹悶鍔嶅姗€鈥﹂崶褜鐓剁紒鍙樿含rrag闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁嶉崟顐㈢亰閻庡厜鍋撻柛鏇ㄥ墮娴犲ジ姊哄ú璁崇凹闁衡偓?rag闂傚倸鍊峰ù鍥敋瑜忛埀顒佺▓閺呮繄鍒掑▎鎾崇婵°倐鍋撶紒鈧径瀣╃箚闁靛牆鍊告禍楣冩煟閹惧崬鈧繈寮婚悢椋庢殝闁瑰嘲鐭堝鑸电箾鐎涙鐭婄紓宥咃躬瀵鏁撻悩鑼€為梺鍝勭墢閺佹悂寮弽顐ょ＝濞达絾褰冩禍?
        if (parent / "hyperrag" / "__init__.py").exists() and (parent / "cog-rag" / "cograg" / "__init__.py").exists():
            if str(parent) not in sys.path:
                sys.path.insert(0, str(parent))
                print("Log message")
            # 濠电姷鏁告慨鐑藉极閹间礁纾块柟瀵稿Х缁€濠囨煃瑜滈崜姘跺Φ閸曨垰鍗抽柛鈩冾殔椤忣亪鏌涘▎蹇曠闁哄矉绲鹃幆鏃堟晬閸曨偅銇焔-rag闂傚倸鍊搁崐鐑芥嚄閸洖纾块柣銏㈩焾閻ょ偓绻濋棃娑氬ⅱ闁活厽鎹囬弻娑滎槼妞ゃ劌妫濋幃锟犲即閵忥紕鍘甸梺缁樺灦钃遍柍閿嬪姍閺岋綁濡堕崟顓犳s.path婵犵數濮烽弫鎼佸磻濞戙埄鏁嬫い鎾跺枑閸欏繐霉閸忓吋缍戠痪鎯ф健閺岀喎鈻撻崹顔界亾闂佹椿鍘藉畝鎼佸蓟濞戙垹绠婚柤濂割杺閸炲綊姊虹粙娆惧剱闁圭懓娲獮鍐╃鐎ｎ偒妫冨┑鐐村灦鐪夌紒顕呭灦濮?
            cog_rag_path = parent / "cog-rag"
            if str(cog_rag_path) not in sys.path:
                sys.path.insert(0, str(cog_rag_path))
                print("Log message")
            break

try:
    # 闂傚倸鍊峰ù鍥敋瑜忛幑銏ゅ箛椤旇棄搴婇梺鐟邦嚟婵潧鐣烽弻銉︾厱闁斥晛鍟伴埊鏇㈡煕鎼粹槄鏀婚柕鍥у瀵粙濡歌閳ь剚甯楅妵鍕煛閸滀焦顥栭梺閫炲苯澧繝鈧柆宥佲偓锕傚醇閵夈儳鍝楃紓浣歌嫰缁鳖枾g闂傚倸鍊峰ù鍥敋瑜嶉湁闁绘垼妫勯弸渚€鏌熼梻瀵割槮闁稿被鍔庨幉鎼佸棘鐠恒劍娈?
    import importlib
    spec = importlib.util.find_spec("cograg")
    if spec:
        from cograg import CogRAG as CogRAGClass, QueryParam as CogQueryParam
        from cograg.utils import EmbeddingFunc
        COGRAG_AVAILABLE = True
        print("Cog-RAG module loaded successfully")
    else:
        raise ImportError("cograg module spec not found")
except ImportError as e:
    print(f"Cog-RAG not available: {e}")
    COGRAG_AVAILABLE = False
    print("Cog-RAG module is not available")

# 闂傚倸鍊峰ù鍥х暦閸偅鍙忕€规洖娲ㄩ惌鍡椕归敐鍫綈婵炲懐濮撮湁闁绘ê妯婇崕鎰版煕鐎ｅ吀閭柡灞剧洴閸╁嫰宕橀浣诡潔婵犵妲呴崑鍛存晝閵忋倕钃熸繛鎴欏灩鍞銈嗙墱閸嬬偤顢撳鍜佹富闁靛牆妫楁慨鍐磼椤旂晫鎳囨鐐插暢閵囨劙骞掗幘鏉戝姃闂備線娼荤€靛矂宕㈤幆褏鏆?
SETTINGS_FILE = os.getenv("HYPERCHE_SETTINGS_FILE", "settings.json")
API_KEY_POOL_STATE = {
    "llm": {"cursor": 0, "disabled": set()},
    "embedding": {"cursor": 0, "disabled": set()},
}
CURRENT_USER_ID = contextvars.ContextVar("hyperche_current_user_id", default=None)
LLM_PROVIDER_POOL_STATE = {
    "cursor": 0,
    "keys": {},
    "providers": {},
}

def get_runtime_settings_context() -> dict:
    """Docstring."""
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            settings = json.load(f)
        return {
            "model": settings.get("modelName"),
            "base_url": settings.get("baseUrl"),
            "embedding_model": settings.get("embeddingModel"),
            "embedding_base_url": settings.get("embeddingBaseUrl"),
            "embedding_dim": settings.get("embeddingDim"),
            "hyperrag_domain": settings.get("hyperrag_domain", "default"),
            "experiment_mode": settings.get("experimentMode", settings.get("experiment_mode", "hyper_final")),
            "prompt_profile": settings.get("promptProfile", settings.get("prompt_profile", "chemistry")),
            "enable_entity_normalization": settings.get("enableEntityNormalization", settings.get("enable_entity_normalization", True)),
            "enable_measurement_instances": settings.get("enableMeasurementInstances", settings.get("enable_measurement_instances", True)),
            "enable_efu_repair": settings.get("enableEfuRepair", settings.get("enable_efu_repair", True)),
            "enable_hybrid_rerank": settings.get("enableHybridRerank", settings.get("enable_hybrid_rerank", True)),
        }
    except Exception as e:
        return {"settings_error": safe_str(e)}

def split_api_keys(value: str | None) -> list[str]:
    """Split multiline, comma, or semicolon separated API keys."""
    if not value:
        return []
    return [item.strip() for item in re.split(r"[\n,;]+", value) if item.strip()]

def mask_api_keys_for_settings(value: str | None) -> str:
    """Return one masked line per configured key so the settings UI preserves key count."""
    keys = split_api_keys(value)
    return "\n".join("***" for _ in keys)

def resolve_masked_api_key_text(new_value: str | None, existing_value: str | None) -> str:
    """Restore masked API key placeholders when saving settings.

    The frontend receives existing keys as one "***" per key. When saving, unchanged
    masked entries are restored from the previous settings while newly typed entries
    are kept. This also lets users add/remove individual keys in a multiline field.
    """
    new_keys = split_api_keys(new_value)
    if not new_keys:
        return ""

    existing_keys = split_api_keys(existing_value)
    if all(key == "***" for key in new_keys):
        if len(new_keys) == len(existing_keys):
            return "\n".join(existing_keys)

    resolved = []
    for index, key in enumerate(new_keys):
        if key == "***":
            if index < len(existing_keys):
                resolved.append(existing_keys[index])
        else:
            resolved.append(key)
    return "\n".join(resolved)

def get_api_key_candidates(pool_name: str, primary: str | None, fallback: str | None = None) -> list[tuple[int, int, str]]:
    keys = split_api_keys(primary)
    if not keys:
        keys = split_api_keys(fallback)
    if not keys:
        return []

    state = API_KEY_POOL_STATE.setdefault(pool_name, {"cursor": 0, "disabled": set()})
    enabled = [(idx, key) for idx, key in enumerate(keys) if key not in state["disabled"]]
    candidates = enabled or list(enumerate(keys))
    start = state["cursor"] % len(candidates)
    state["cursor"] += 1
    ordered = candidates[start:] + candidates[:start]
    return [(idx + 1, len(keys), key) for idx, key in ordered]

def mark_api_key_unhealthy(pool_name: str, key: str, error_message: str) -> None:
    error_lower = error_message.lower()
    if (
        "permissiondenied" in error_lower
        or "permission denied" in error_lower
        or "insufficient" in error_lower
        or "balance" in error_lower
        or "quota" in error_lower
        or "401" in error_message
        or "403" in error_message
    ):
        API_KEY_POOL_STATE.setdefault(pool_name, {"cursor": 0, "disabled": set()})["disabled"].add(key)

def reset_api_key_pool_health(pool_name: str | None = None) -> None:
    pools = [pool_name] if pool_name else list(API_KEY_POOL_STATE.keys())
    for pool in pools:
        API_KEY_POOL_STATE.setdefault(pool, {"cursor": 0, "disabled": set()})["disabled"].clear()

def summarize_key_pool(pool_name: str, primary: str | None, fallback: str | None = None) -> dict:
    keys = split_api_keys(primary) or split_api_keys(fallback)
    disabled = API_KEY_POOL_STATE.setdefault(pool_name, {"cursor": 0, "disabled": set()})["disabled"]
    return {
        "pool": pool_name,
        "total_keys": len(keys),
        "disabled_keys": sum(1 for key in keys if key in disabled),
        "enabled_keys": sum(1 for key in keys if key not in disabled),
    }

def _coerce_positive_int(value: Any, default: int, minimum: int = 1) -> int:
    try:
        parsed = int(value)
        return parsed if parsed >= minimum else default
    except Exception:
        return default

def _fingerprint_key(key: str | None) -> str:
    if not key:
        return "nokey"
    return hashlib.sha256(key.encode("utf-8", errors="ignore")).hexdigest()[:12]

def _provider_id(provider: dict) -> str:
    return "|".join(
        [
            safe_str(provider.get("name", "")),
            safe_str(provider.get("baseUrl", "")),
            safe_str(provider.get("modelName", "")),
        ]
    )

def _llm_key_id(provider: dict, key_index: int, key: str | None) -> str:
    return f"{_provider_id(provider)}|{key_index}|{_fingerprint_key(key)}"

def normalize_llm_providers(settings: dict) -> list[dict]:
    """Build enabled OpenAI-compatible LLM provider configs with legacy fallback."""
    per_key_default = _coerce_positive_int(settings.get("llmPerKeyMaxAsync", 1), 1)
    global_default = _coerce_positive_int(
        settings.get("llmGlobalMaxAsync", settings.get("llmModelMaxAsync", 4)),
        4,
    )

    raw_providers = settings.get("llmProviders")
    providers: list[dict] = []
    if isinstance(raw_providers, list):
        for idx, raw in enumerate(raw_providers):
            if not isinstance(raw, dict):
                continue
            api_keys = raw.get("apiKeys", [])
            if isinstance(api_keys, str):
                api_keys = split_api_keys(api_keys)
            elif isinstance(api_keys, list):
                api_keys = [safe_str(key).strip() for key in api_keys if safe_str(key).strip()]
            else:
                api_keys = []

            provider = {
                "name": raw.get("name") or f"llm-provider-{idx + 1}",
                "baseUrl": raw.get("baseUrl") or settings.get("baseUrl"),
                "modelName": raw.get("modelName") or settings.get("modelName", "gpt-5-mini"),
                "apiKeys": api_keys,
                "enabled": raw.get("enabled", True) is not False,
                "maxAsync": _coerce_positive_int(raw.get("maxAsync"), max(1, len(api_keys) * per_key_default)),
                "perKeyMaxAsync": _coerce_positive_int(raw.get("perKeyMaxAsync", per_key_default), per_key_default),
                "priority": _coerce_positive_int(raw.get("priority", 100), 100, minimum=0),
                "index": idx,
            }
            if provider["enabled"] and provider["baseUrl"] and provider["modelName"]:
                providers.append(provider)

    if not providers:
        legacy_keys = split_api_keys(settings.get("apiKey"))
        providers.append(
            {
                "name": "legacy-llm",
                "baseUrl": settings.get("baseUrl"),
                "modelName": settings.get("modelName", "gpt-5-mini"),
                "apiKeys": legacy_keys,
                "enabled": True,
                "maxAsync": max(1, min(global_default, max(1, len(legacy_keys) * per_key_default))),
                "perKeyMaxAsync": per_key_default,
                "priority": 100,
                "index": 0,
            }
        )

    return providers

def _pool_record(bucket: str, item_id: str, limit: int) -> dict:
    records = LLM_PROVIDER_POOL_STATE.setdefault(bucket, {})
    record = records.get(item_id)
    if record is None or record.get("limit") != limit:
        # Recreate only the limiter metadata; health state lives in the key record.
        record = {
            "limit": limit,
            "semaphore": asyncio.Semaphore(max(1, limit)),
            "active": 0,
        }
        records[item_id] = record
    return record

def _key_health_record(candidate: dict) -> dict:
    records = LLM_PROVIDER_POOL_STATE.setdefault("keys", {})
    item_id = candidate["key_id"]
    return records.setdefault(
        item_id,
        {
            "disabled": False,
            "cooldown_until": 0.0,
            "last_error": "",
            "success_count": 0,
            "failure_count": 0,
            "timeout_count": 0,
            "avg_latency": 0.0,
        },
    )

def classify_llm_pool_error(error_message: str) -> str:
    error_lower = error_message.lower()
    if (
        "permissiondenied" in error_lower
        or "permission denied" in error_lower
        or "insufficient" in error_lower
        or "balance" in error_lower
        or "quota" in error_lower
        or "unauthorized" in error_lower
        or "authentication" in error_lower
        or "401" in error_message
        or "403" in error_message
    ):
        return "disable"
    if "429" in error_message or "rate" in error_lower or "limit" in error_lower:
        return "cooldown"
    if (
        "connection" in error_lower
        or "network" in error_lower
        or "500" in error_message
        or "502" in error_message
        or "503" in error_message
        or "504" in error_message
    ):
        return "cooldown"
    return "fail"

def summarize_llm_provider_pool(settings: dict) -> dict:
    providers = normalize_llm_providers(settings)
    total_keys = 0
    enabled_keys = 0
    disabled_keys = 0
    cooldown_keys = 0
    now = time.monotonic()
    details = []
    for provider in providers:
        keys = provider.get("apiKeys") or [None]
        provider_total = len(keys)
        provider_enabled = 0
        provider_disabled = 0
        provider_cooldown = 0
        for key_index, key in enumerate(keys, start=1):
            candidate = {
                "provider": provider,
                "key_index": key_index,
                "key_id": _llm_key_id(provider, key_index, key),
            }
            health = _key_health_record(candidate)
            total_keys += 1
            if health.get("disabled"):
                disabled_keys += 1
                provider_disabled += 1
            elif health.get("cooldown_until", 0.0) > now:
                cooldown_keys += 1
                provider_cooldown += 1
            else:
                enabled_keys += 1
                provider_enabled += 1
        details.append(
            {
                "name": provider.get("name"),
                "model": provider.get("modelName"),
                "base_url": provider.get("baseUrl"),
                "total_keys": provider_total,
                "enabled_keys": provider_enabled,
                "disabled_keys": provider_disabled,
                "cooldown_keys": provider_cooldown,
                "max_async": provider.get("maxAsync"),
                "per_key_max_async": provider.get("perKeyMaxAsync"),
                "priority": provider.get("priority"),
            }
        )
    return {
        "pool": "llm_providers",
        "providers": len(providers),
        "total_keys": total_keys,
        "enabled_keys": enabled_keys,
        "disabled_keys": disabled_keys,
        "cooldown_keys": cooldown_keys,
        "details": details,
    }

def get_llm_provider_candidates(settings: dict) -> list[dict]:
    providers = sorted(normalize_llm_providers(settings), key=lambda item: (item.get("priority", 100), item.get("index", 0)))
    now = time.monotonic()
    candidates: list[dict] = []
    for provider_pos, provider in enumerate(providers, start=1):
        keys = provider.get("apiKeys") or [None]
        key_total = len(keys)
        for key_index, key in enumerate(keys, start=1):
            candidate = {
                "provider": provider,
                "provider_index": provider_pos,
                "provider_total": len(providers),
                "key": key,
                "key_index": key_index,
                "key_total": key_total,
                "provider_id": _provider_id(provider),
                "key_id": _llm_key_id(provider, key_index, key),
            }
            health = _key_health_record(candidate)
            if health.get("disabled"):
                continue
            if health.get("cooldown_until", 0.0) > now:
                continue
            candidates.append(candidate)

    if not candidates:
        return []
    start = LLM_PROVIDER_POOL_STATE.get("cursor", 0) % len(candidates)
    LLM_PROVIDER_POOL_STATE["cursor"] = LLM_PROVIDER_POOL_STATE.get("cursor", 0) + 1
    return candidates[start:] + candidates[:start]

async def acquire_llm_provider_slot(candidate: dict):
    provider = candidate["provider"]
    provider_record = _pool_record("providers", candidate["provider_id"], provider.get("maxAsync", 1))
    key_record = _pool_record("key_slots", candidate["key_id"], provider.get("perKeyMaxAsync", 1))
    await provider_record["semaphore"].acquire()
    provider_record["active"] += 1
    try:
        await key_record["semaphore"].acquire()
        key_record["active"] += 1
    except Exception:
        provider_record["active"] -= 1
        provider_record["semaphore"].release()
        raise

    def release():
        try:
            key_record["active"] = max(0, key_record["active"] - 1)
            key_record["semaphore"].release()
        finally:
            provider_record["active"] = max(0, provider_record["active"] - 1)
            provider_record["semaphore"].release()

    return release, provider_record, key_record

def record_llm_provider_result(candidate: dict, status: str, duration: float | None = None, error_message: str | None = None, cooldown_seconds: int = 60) -> str:
    health = _key_health_record(candidate)
    action = "none"
    if status == "success":
        health["success_count"] += 1
        if duration is not None:
            previous = float(health.get("avg_latency", 0.0) or 0.0)
            health["avg_latency"] = duration if previous <= 0 else previous * 0.8 + duration * 0.2
        health["last_error"] = ""
        action = "healthy"
    elif status == "timeout":
        health["timeout_count"] += 1
        health["last_error"] = error_message or "timeout"
        action = "record_timeout"
    else:
        health["failure_count"] += 1
        health["last_error"] = error_message or status
        action = classify_llm_pool_error(error_message or "")
        if action == "disable":
            health["disabled"] = True
        elif action == "cooldown":
            health["cooldown_until"] = time.monotonic() + max(1, cooldown_seconds)
    return action

def reset_llm_provider_pool_health() -> None:
    for record in LLM_PROVIDER_POOL_STATE.setdefault("keys", {}).values():
        record["disabled"] = False
        record["cooldown_until"] = 0.0
        record["last_error"] = ""

enable_api_docs = os.getenv("HYPERCHE_ENABLE_API_DOCS", "false").lower() in {"1", "true", "yes"}
app = FastAPI(
    docs_url="/docs" if enable_api_docs else None,
    redoc_url="/redoc" if enable_api_docs else None,
    openapi_url="/openapi.json" if enable_api_docs else None,
)

def _cors_origins() -> list[str]:
    configured = os.getenv("CORS_ORIGINS", "")
    if configured:
        return [origin.strip() for origin in configured.split(",") if origin.strip()]
    return [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5000",
        "http://127.0.0.1:5000",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def log_http_requests(request: Request, call_next):
    start = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        duration_ms = (time.perf_counter() - start) * 1000
        path = request.url.path
        if path.startswith(("/files", "/auth", "/quota", "/settings", "/hyperrag")):
            log_line = (
                f"HTTP {request.method} {path} status={status_code} "
                f"duration_ms={duration_ms:.1f}"
            )
            if status_code >= 400:
                main_logger.warning(log_line)
            else:
                main_logger.info(log_line)

@app.get("/")
async def root():
    return {"message": "HyperChE"}


class AuthRegisterRequest(BaseModel):
    email: str
    password: str
    display_name: str = ""


class AuthLoginRequest(BaseModel):
    email: str
    password: str


class QuotaConfigRequest(BaseModel):
    trial_docs_limit: int = 3
    trial_llm_calls_limit: int = 50
    trial_embedding_calls_limit: int = 200


class UserApiKeyRequest(BaseModel):
    provider_type: str
    base_url: str
    model_name: str
    api_key: str
    enabled: bool = True


def public_user(user: dict) -> dict:
    return {
        "id": user.get("id"),
        "email": user.get("email"),
        "display_name": user.get("display_name"),
        "role": user.get("role", "user"),
    }


def _set_auth_cookie(response: Response, token: str) -> None:
    secure_cookie = os.getenv("COOKIE_SECURE", "false").lower() == "true"
    response.set_cookie(
        AUTH_COOKIE_NAME,
        token,
        httponly=True,
        secure=secure_cookie,
        samesite="lax",
        max_age=14 * 24 * 3600,
        path="/",
    )


def _extract_auth_token(request: Request) -> str | None:
    cookie_token = request.cookies.get(AUTH_COOKIE_NAME)
    if cookie_token:
        return cookie_token
    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return None


async def get_current_user(request: Request) -> dict | None:
    user = auth_store.user_from_token(_extract_auth_token(request))
    if user:
        CURRENT_USER_ID.set(user["id"])
    else:
        CURRENT_USER_ID.set(None)
    return user


async def require_current_user(request: Request) -> dict:
    user = await get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return user


async def require_admin_user(user: dict = Depends(require_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")
    return user


def _user_db_prefix(user: dict) -> str:
    user_id = (user or {}).get("id") or "anonymous"
    return f"u_{user_id[:12]}__"


def namespace_database_name(database_name: str | None, user: dict) -> str:
    clean_name = file_manager.sanitize_database_name(database_name or "default")
    prefix = _user_db_prefix(user)
    if clean_name.startswith(prefix):
        return clean_name
    return f"{prefix}{clean_name}"


def user_can_access_database(user: dict, database_name: str | None, include_legacy: bool = True) -> bool:
    if not database_name:
        return True
    if user.get("role") == "admin":
        return True
    if database_name.startswith(_user_db_prefix(user)):
        return True

    user_id = user.get("id")
    for kb in getattr(kb_manager, "_load_metadata", lambda: {})().values():
        if kb.get("database_name") == database_name:
            owner = kb.get("owner_user_id")
            return owner == user_id or (include_legacy and not owner)
    for file_info in file_manager.get_all_files(owner_user_id=user_id, include_legacy=include_legacy):
        if file_info.get("database_name") == database_name:
            return True
    return include_legacy and not database_name.startswith("u_")


def require_database_access(database_name: str | None, user: dict) -> str | None:
    if not database_name:
        return None
    clean_name = file_manager.sanitize_database_name(database_name)
    if not user_can_access_database(user, clean_name):
        raise HTTPException(status_code=403, detail="Forbidden")
    return clean_name


def database_display_name(database_name: str, user: dict) -> str:
    prefix = _user_db_prefix(user)
    if database_name and database_name.startswith(prefix):
        return database_name[len(prefix):]
    return database_name


def has_personal_provider(user_id: str | None, provider_type: str) -> bool:
    return bool(auth_store.get_enabled_providers(user_id, provider_type))


def get_user_llm_provider_candidates(user_id: str | None, settings: dict) -> list[dict]:
    user_providers = auth_store.get_enabled_providers(user_id, "llm")
    if not user_providers:
        return []

    per_key_default = _coerce_positive_int(settings.get("llmPerKeyMaxAsync", 1), 1)
    providers = []
    for idx, user_provider in enumerate(user_providers):
        api_keys = user_provider.get("apiKeys") or split_api_keys(user_provider.get("apiKey"))
        if not api_keys:
            continue
        providers.append(
            {
                "name": f"user-llm-{idx + 1}",
                "baseUrl": user_provider["baseUrl"],
                "modelName": user_provider["modelName"],
                "apiKeys": api_keys,
                "enabled": True,
                "maxAsync": max(1, len(api_keys) * per_key_default),
                "perKeyMaxAsync": per_key_default,
                "priority": idx,
                "index": idx,
            }
        )
    if not providers:
        return []

    user_settings = dict(settings)
    user_settings["llmProviders"] = providers
    return get_llm_provider_candidates(user_settings)


def summarize_user_provider_pool(user_id: str | None, provider_type: str) -> dict:
    providers = auth_store.get_enabled_providers(user_id, provider_type)
    return {
        "pool": f"user_{provider_type}",
        "providers": len(providers),
        "total_keys": sum(len(provider.get("apiKeys") or []) for provider in providers),
    }


def get_user_embedding_candidates(user_id: str | None, settings: dict) -> list[dict]:
    user_providers = auth_store.get_enabled_providers(user_id, "embedding")
    candidates = []
    for provider_index, provider in enumerate(user_providers, start=1):
        key_candidates = get_api_key_candidates(
            f"embedding:user:{provider.get('id', provider_index)}",
            "\n".join(provider.get("apiKeys") or []),
        )
        for key_index, key_total, candidate_key in key_candidates:
            candidates.append(
                {
                    "provider_index": provider_index,
                    "provider_total": len(user_providers),
                    "key_index": key_index,
                    "key_total": key_total,
                    "key": candidate_key,
                    "model": provider["modelName"],
                    "base_url": provider["baseUrl"],
                }
            )
    return candidates


def consume_platform_quota(user_id: str | None, provider_type: str, amount: int = 1) -> None:
    if not user_id:
        return
    if has_personal_provider(user_id, provider_type):
        return
    quota_type = "llm" if provider_type == "llm" else "embedding"
    try:
        auth_store.consume_quota(user_id, quota_type, amount)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=safe_str(e))


def consume_document_quota_if_needed(user: dict, file_count: int) -> None:
    user_id = user.get("id")
    if user_id and not has_personal_provider(user_id, "embedding"):
        try:
            auth_store.consume_quota(user_id, "docs", file_count)
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=safe_str(e))


@app.post("/auth/register")
async def auth_register(payload: AuthRegisterRequest, response: Response):
    try:
        user = auth_store.create_user(payload.email, payload.password, payload.display_name)
        token = create_token(user["id"], user.get("role", "user"))
        _set_auth_cookie(response, token)
        CURRENT_USER_ID.set(user["id"])
        return {"success": True, "user": public_user(user), "quota": auth_store.get_quota(user["id"])}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=safe_str(e))


@app.post("/auth/login")
async def auth_login(payload: AuthLoginRequest, response: Response):
    user = auth_store.authenticate(payload.email, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_token(user["id"], user.get("role", "user"))
    _set_auth_cookie(response, token)
    CURRENT_USER_ID.set(user["id"])
    return {"success": True, "user": public_user(user), "quota": auth_store.get_quota(user["id"])}


@app.post("/auth/logout")
async def auth_logout(response: Response):
    secure_cookie = os.getenv("COOKIE_SECURE", "false").lower() == "true"
    response.delete_cookie(AUTH_COOKIE_NAME, path="/", secure=secure_cookie, httponly=True, samesite="lax")
    CURRENT_USER_ID.set(None)
    return {"success": True}


@app.get("/auth/me")
async def auth_me(user: dict = Depends(require_current_user)):
    return {"success": True, "user": public_user(user), "quota": auth_store.get_quota(user["id"])}


@app.get("/quota/me")
async def quota_me(user: dict = Depends(require_current_user)):
    return {"success": True, "quota": auth_store.get_quota(user["id"])}


@app.get("/admin/quota-config")
async def get_admin_quota_config(user: dict = Depends(require_admin_user)):
    return {"success": True, "quota_config": auth_store.get_quota_limits()}


@app.post("/admin/quota-config")
async def save_admin_quota_config(payload: QuotaConfigRequest, user: dict = Depends(require_admin_user)):
    limits = auth_store.set_quota_limits(
        payload.trial_docs_limit,
        payload.trial_llm_calls_limit,
        payload.trial_embedding_calls_limit,
    )
    return {"success": True, "quota_config": limits}


@app.get("/user-api-keys")
async def list_user_api_keys(user: dict = Depends(require_current_user)):
    return {"success": True, "keys": auth_store.list_api_keys(user["id"])}


@app.post("/user-api-keys")
async def create_user_api_key(payload: UserApiKeyRequest, user: dict = Depends(require_current_user)):
    try:
        key = auth_store.add_api_key(
            user["id"],
            payload.provider_type,
            payload.base_url,
            payload.model_name,
            payload.api_key,
            payload.enabled,
        )
        return {"success": True, "key": key}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=safe_str(e))


@app.delete("/user-api-keys/{key_id}")
async def delete_user_api_key(key_id: str, user: dict = Depends(require_current_user)):
    deleted = auth_store.delete_api_key(user["id"], key_id)
    return {"success": deleted}


# ============ Knowledge Base Management ============

kb_manager = KnowledgeBaseManager()

class KBCreateRequest(BaseModel):
    name: str
    description: str = ""
    rag_system: str = "hyperrag"
    domain: str = "default"
    chunk_size: int = 1000
    chunk_overlap: int = 200

class KBUpdateRequest(BaseModel):
    description: Optional[str] = None
    rag_system: Optional[str] = None
    domain: Optional[str] = None
    chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None
    name: Optional[str] = None

@app.post("/kb")
async def create_kb(req: KBCreateRequest, user: dict = Depends(require_current_user)):
    """Docstring."""
    try:
        kb = await kb_manager.create_kb(
            name=req.name,
            description=req.description,
            rag_system=req.rag_system,
            domain=req.domain,
            chunk_size=req.chunk_size,
            chunk_overlap=req.chunk_overlap,
            database_name=namespace_database_name(req.name, user),
            owner_user_id=user.get("id"),
        )
        return {"success": True, "data": kb}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=safe_str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_str(e))

@app.get("/kb")
async def list_kbs(user: dict = Depends(require_current_user)):
    """Docstring."""
    try:
        kbs = await kb_manager.list_kbs(owner_user_id=user.get("id"), include_legacy=True)
        result = []
        for kb in kbs:
            stats = await kb_manager.get_kb_stats(kb["database_name"], file_manager, owner_user_id=user.get("id"), include_legacy=True)
            result.append({**kb, "display_database_name": database_display_name(kb["database_name"], user), "stats": stats})
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_str(e))

@app.get("/kb/{kb_name}")
async def get_kb(kb_name: str, user: dict = Depends(require_current_user)):
    """Docstring."""
    try:
        kb = await kb_manager.get_kb(kb_name, owner_user_id=user.get("id"), include_legacy=True)
        if not kb:
            raise HTTPException(status_code=404, detail="Knowledge base not found")
        stats = await kb_manager.get_kb_stats(kb["database_name"], file_manager, owner_user_id=user.get("id"), include_legacy=True)
        return {**kb, "display_database_name": database_display_name(kb["database_name"], user), "stats": stats}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_str(e))

@app.put("/kb/{kb_name}")
async def update_kb(kb_name: str, req: KBUpdateRequest, user: dict = Depends(require_current_user)):
    """Docstring."""
    try:
        updates = {k: v for k, v in req.dict().items() if v is not None}
        kb = await kb_manager.update_kb(kb_name, owner_user_id=user.get("id"), include_legacy=True, **updates)
        if not kb:
            raise HTTPException(status_code=404, detail="Knowledge base not found")
        return {"success": True, "data": kb}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_str(e))

@app.delete("/kb/{kb_name}")
async def delete_kb(kb_name: str, user: dict = Depends(require_current_user)):
    """Docstring."""
    try:
        kb = await kb_manager.get_kb(kb_name, owner_user_id=user.get("id"), include_legacy=True)
        if not kb:
            raise HTTPException(status_code=404, detail="Knowledge base not found")
        database_name = kb["database_name"]

        # 闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁嶉崟顒佹闂佺粯鍔曢顓犵不妤ｅ啯鐓冪憸婊堝礈濮樿鲸宕叉繛鎴欏灩瀹告繃銇勯幘鍗炵仼鐎殿喕鍗抽幃妤冩喆閸曨剛顦ㄥ銈冨妼閻楁捇宕洪埀顒併亜閹哄棗浜惧┑鐘亾閺夊牄鍔嶉崣蹇曗偓瑙勬礀濞层倝宕瑰┑瀣厵闁告挆鍛闂佺粯鎸婚惄顖炲蓟濞戞矮娌柛鎾楀本娈归梻浣规た閸樹粙銆冮崱娆愬床?
        all_files = file_manager.get_all_files(owner_user_id=user.get("id"), include_legacy=True)
        kb_files = [f for f in all_files if f.get("kb_name") == database_name]
        for f in kb_files:
            try:
                file_manager.delete_file(f["file_id"])
            except Exception:
                pass

        # 闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁嶉崟顒佹闂佺粯鍔曢顓犵不妤ｅ啯鐓冪憸婊堝礈濮樿鲸宕叉繛鎴欏灩瀹告繃銇勯幘鍗炵仼鐎殿喕鍗抽幃妤€鈻撻崹顔界彯闂佺顑呴敃顏堢嵁閸愵収妯勯悗瑙勬礈閸樠囧煘閹达箑閱囨繛鎴灻奸崰濠囨⒒?
        try:
            db_manager.delete_database(database_name)
        except Exception:
            pass

        # 闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁嶉崟顒佹闂佺粯鍔曢顓犵不妤ｅ啯鐓冪憸婊堝礈濮樿鲸宕叉繛鎴欏灩瀹告繃銇勯幘璺轰粶闁哄棭鎼遍梻鍌氬€搁崐鐑芥嚄閸洍鈧箓宕奸姀鈥冲簥闂佸湱澧楀姗€鎮块濮愪簻闁哄稁鍋勬禒婊勬叏鐟欏嫮鍙€闁哄矉缍佸顕€宕掑顑跨帛缂?
        await kb_manager.delete_kb(kb_name, owner_user_id=user.get("id"), include_legacy=True)

        return {"success": True, "message": f"Knowledge base {kb_name} deleted"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_str(e))


@app.get("/db")
async def db(database: str = None, user: dict = Depends(require_current_user)):
    """
    闂傚倸鍊搁崐椋庣矆娓氣偓瀹曘儳鈧綆鍠栫壕鍧楁煙閹増顥夐幖鏉戯躬閺屻倝鎳濋幍顔肩墯婵炲瓨绮岀紞濠囧蓟濞戙垹唯妞ゆ梻鍘ч～鈺冪磽娴ｆ彃浜鹃梺绋跨灱閸嬬偤鎮¤箛鎾斀闁绘劙娼ф禍鐐箾閸涱厽鍤囬柡灞剧洴瀵剛鎷犻幓鎺懶曢梻浣告惈婢跺洭宕滃┑瀣闁告稒娼欐导鐘绘煕閺囩偟浠涙慨锝咁樀閺岋絾鎯旈妶搴㈢秷闂佸湱顭堥崲鍙夋櫏闂佽娴烽埀顒佄?
    """
    try:
        database = require_database_access(database, user)
        data = get_hypergraph(database)
        return data
    except Exception as e:
        return {"error": safe_str(e)}

@app.get("/db/vertices")
async def get_vertices_function(database: str = None, page: int = None, page_size: int = None, user: dict = Depends(require_current_user)):
    """
    闂傚倸鍊搁崐椋庣矆娓氣偓瀹曘儳鈧綆鍠栫壕鍧楁煙閹増顥夐幖鏉戯躬閺屻倝鎳濋幍顔肩墯婵炲瓨绮岀紞濠囧蓟濞戙垺鏅查柛鈩冾焺椤ょices闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁嶉崟顒佹濠德板€曢幊宀勫焵椤掆偓閸燁垰顕ラ崟顖氱疀妞?
    """
    try:
        database = require_database_access(database, user)
        data = getFrequentVertices(database, page, page_size)
        return data
    except Exception as e:
        return {"error": safe_str(e)}

@app.get("/db/hyperedges")
async def get_hypergraph_function(database: str = None, page: int = None, page_size: int = None, user: dict = Depends(require_current_user)):
    """
    闂傚倸鍊搁崐椋庣矆娓氣偓瀹曘儳鈧綆鍠栫壕鍧楁煙閹増顥夐幖鏉戯躬閺屻倝鎳濋幍顔肩墯婵炲瓨绮岀紞濠囧蓟濞戙垺鏅查柛娑卞幖椤尩eredges闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁嶉崟顒佹濠德板€曢幊宀勫焵椤掆偓閸燁垰顕ラ崟顖氱疀妞?
    """
    try:
        database = require_database_access(database, user)
        data = get_hyperedges(database, page, page_size)
        return data
    except Exception as e:
        return {"error": safe_str(e)}

@app.get("/db/hyperedges/{hyperedge_id}")
async def get_hyperedge(hyperedge_id: str, database: str = None, user: dict = Depends(require_current_user)):
    """
    闂傚倸鍊搁崐椋庣矆娓氣偓瀹曘儳鈧綆鍠栫壕鍧楁煙閹増顥夐幖鏉戯躬閺屻倝鎳濋幍顔肩墯婵炲瓨绮岀紞濠囧蓟濞戙垹唯妞ゆ梻鍘ч～鈺冪磽娴ｅ搫小闁告濞婂璇测槈閵忕姈銊╂煙鐎涙绠栭柛锝囧劋閹便劑鏁愰崨顖楁晢yperedge闂傚倸鍊搁崐鐑芥倿閿曞倹鍎戠憸鐗堝笒缁€澶屸偓鍏夊亾闁逞屽墴閸┾偓妞ゆ帊绀侀崵顒勬煕閵娿儳鍩ｇ€?
    """
    try:
        hyperedge_id = hyperedge_id.replace("%20", " ")
        vertices = hyperedge_id.split("|*|")
        database = require_database_access(database, user)
        data = get_hyperedge_detail(vertices, database)
        return data
    except Exception as e:
        return {"error": safe_str(e)}

@app.get("/db/vertices/{vertex_id}")
async def get_vertex(vertex_id: str, database: str = None, user: dict = Depends(require_current_user)):
    """
    闂傚倸鍊搁崐椋庣矆娓氣偓瀹曘儳鈧綆鍠栫壕鍧楁煙閹増顥夐幖鏉戯躬閺屻倝鎳濋幍顔肩墯婵炲瓨绮岀紞濠囧蓟濞戙垹唯妞ゆ梻鍘ч～鈺冪磽娴ｅ搫小闁告濞婂璇测槈閵忕姈銊╂煙鐎涙绠栭柛锝囧劋閹便劑鏁愰崨顖滃床ertex闂傚倸鍊搁崐鐑芥倿閿曞倹鍎戠憸鐗堝笒缁€澶屸偓鍏夊亾闁告洦鍋呭Σ顒佺節绾版ê澧查柡鈧化?
    """
    vertex_id = vertex_id.replace("%20", " ")
    try:
        database = require_database_access(database, user)
        data = get_vertice(vertex_id, database)
        return data
    except Exception as e:
        return {"error": safe_str(e)}

@app.get("/db/vertices_neighbor/{vertex_id}")
async def get_vertex_neighbor(vertex_id: str, database: str = None, user: dict = Depends(require_current_user)):
    """
    闂傚倸鍊搁崐椋庣矆娓氣偓瀹曘儳鈧綆鍠栫壕鍧楁煙閹増顥夐幖鏉戯躬閺屻倝鎳濋幍顔肩墯婵炲瓨绮岀紞濠囧蓟濞戙垹唯妞ゆ梻鍘ч～鈺冪磽娴ｅ搫小闁告濞婂璇测槈閵忕姈銊╂煙鐎涙绠栭柛锝囧劋閹便劑鏁愰崨顖滃床ertex闂傚倸鍊搁崐鐑芥倿閿曞倹鍎戠憸鐗堝笒缁€澶屸偓鍏夊亾闁告洦鍋呭Σ顒勬⒑閸濆嫷妲搁柛鈺佹hbor
    """
    vertex_id = vertex_id.replace("%20", " ")
    try:
        database = require_database_access(database, user)
        data = get_vertice_neighbor(vertex_id, database)
        return data
    except Exception as e:
        return {"error": safe_str(e)}

@app.get("/db/hyperedge_neighbor/{hyperedge_id}")
async def get_hyperedge_neighbor(hyperedge_id: str, database: str = None, user: dict = Depends(require_current_user)):
    """
    闂傚倸鍊搁崐椋庣矆娓氣偓瀹曘儳鈧綆鍠栫壕鍧楁煙閹増顥夐幖鏉戯躬閺屻倝鎳濋幍顔肩墯婵炲瓨绮岀紞濠囧蓟濞戙垹唯妞ゆ梻鍘ч～鈺冪磽娴ｅ搫小闁告濞婂璇测槈閵忕姈銊╂煙鐎涙绠栭柛锝囧劋閹便劑鏁愰崨顖楁晢yperedge闂傚倸鍊搁崐鐑芥倿閿曞倹鍎戠憸鐗堝笒缁€澶屸偓鍏夊亾闁告洦鍋呭Σ顒勬⒑閸濆嫷妲搁柛鈺佹hbor
    """
    hyperedge_id = hyperedge_id.replace("%20", " ")
    hyperedge_id = hyperedge_id.replace("*", "#")
    print(hyperedge_id)
    try:
        database = require_database_access(database, user)
        data = get_hyperedge_neighbor_server(hyperedge_id, database)
        return data
    except Exception as e:
        return {"error": safe_str(e)}

class VertexModel(BaseModel):
    vertex_id: str
    entity_name: str = ""
    entity_type: str = ""
    description: str = ""
    additional_properties: str = ""
    database: str = None

class HyperedgeModel(BaseModel):
    vertices: list
    keywords: str = ""
    summary: str = ""
    database: str = None

class VertexUpdateModel(BaseModel):
    entity_name: str = ""
    entity_type: str = ""
    description: str = ""
    additional_properties: str = ""
    database: str = None

class HyperedgeUpdateModel(BaseModel):
    keywords: str = ""
    summary: str = ""
    database: str = None

@app.post("/db/vertices")
async def create_vertex(vertex: VertexModel, user: dict = Depends(require_current_user)):
    """
    闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁嶉崟顒佹濠德板€曢崯浼存儗濞嗘挻鐓欓悗鐢殿焾鍟哥紒鎯у綖缁瑩寮婚悢鐓庣闁逛即娼у▓顓炩攽閳藉棗浜濋柨鏇樺灲瀵鎮㈢亸浣圭亖闂佸壊鐓堥崰妤呮倶瀹ュ鈷戝ù鍏肩懅閹吋绻濋埀顒勬倵瀹勭ex
    """
    try:
        vertex.database = require_database_access(vertex.database, user)
        result = add_vertex(vertex.vertex_id, {
            "entity_name": vertex.entity_name,
            "entity_type": vertex.entity_type,
            "description": vertex.description,
            "additional_properties": vertex.additional_properties
        }, vertex.database)
        return {"success": True, "message": "Vertex created successfully", "data": result}
    except Exception as e:
        return {"success": False, "message": safe_str(e)}

@app.post("/db/hyperedges")
async def create_hyperedge(hyperedge: HyperedgeModel, user: dict = Depends(require_current_user)):
    """
    闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁嶉崟顒佹濠德板€曢崯浼存儗濞嗘挻鐓欓悗鐢殿焾鍟哥紒鎯у綖缁瑩寮婚悢鐓庣闁逛即娼у▓顓炩攽閳藉棗浜濋柨鏇樺灲瀵鎮㈢亸浣圭亖闂佸壊鐓堥崰妤呮倶瀹ュ鈷戝ù鍏肩懅閹吋绻濋埀顒勫船濠曠櫝redge
    """
    try:
        hyperedge.database = require_database_access(hyperedge.database, user)
        result = add_hyperedge(hyperedge.vertices, {
            "keywords": hyperedge.keywords,
            "summary": hyperedge.summary
        }, hyperedge.database)
        return {"success": True, "message": "Hyperedge created successfully", "data": result}
    except Exception as e:
        return {"success": False, "message": safe_str(e)}

@app.put("/db/vertices/{vertex_id}")
async def update_vertex_endpoint(vertex_id: str, vertex: VertexUpdateModel, user: dict = Depends(require_current_user)):
    """
    闂傚倸鍊搁崐椋庣矆娓氣偓楠炴牠顢曢埛姘そ婵¤埖寰勭€ｎ亙妲愰梻渚€娼ц墝闁哄懏鐩幏鎴︽偄鐏忎焦鏂€闂佹枼鏅涢崯浼村箺閻滅ex婵犵數濮烽弫鎼佸磿閹寸姴绶ら柦妯侯棦濞差亝鍋愰悹鍥皺椤︻厼鈹戦悩缁樻锭婵炲眰鍊濋、?
    """
    try:
        vertex_id = vertex_id.replace("%20", " ")
        vertex.database = require_database_access(vertex.database, user)
        result = update_vertex(vertex_id, {
            "entity_name": vertex.entity_name,
            "entity_type": vertex.entity_type,
            "description": vertex.description,
            "additional_properties": vertex.additional_properties
        }, vertex.database)
        return {"success": True, "message": "Vertex updated successfully", "data": result}
    except Exception as e:
        return {"success": False, "message": safe_str(e)}

@app.put("/db/hyperedges/{hyperedge_id}")
async def update_hyperedge_endpoint(hyperedge_id: str, hyperedge: HyperedgeUpdateModel, user: dict = Depends(require_current_user)):
    """
    闂傚倸鍊搁崐椋庣矆娓氣偓楠炴牠顢曢埛姘そ婵¤埖寰勭€ｎ亙妲愰梻渚€娼ц墝闁哄懏鐩幏鎴︽偄鐏忎焦鏂€闂佺鏈划搴ㄦ偘濮掋€唕edge婵犵數濮烽弫鎼佸磿閹寸姴绶ら柦妯侯棦濞差亝鍋愰悹鍥皺椤︻厼鈹戦悩缁樻锭婵炲眰鍊濋、?
    """
    try:
        hyperedge_id = hyperedge_id.replace("%20", " ")
        vertices = hyperedge_id.split("|*|")
        hyperedge.database = require_database_access(hyperedge.database, user)
        result = update_hyperedge(vertices, {
            "keywords": hyperedge.keywords,
            "summary": hyperedge.summary
        }, hyperedge.database)
        return {"success": True, "message": "Hyperedge updated successfully", "data": result}
    except Exception as e:
        return {"success": False, "message": safe_str(e)}

@app.delete("/db/vertices/{vertex_id}")
async def delete_vertex_endpoint(vertex_id: str, database: str = None, user: dict = Depends(require_current_user)):
    """
    闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁嶉崟顒佹闂佺粯鍔曢顓犵不妤ｅ啯鐓冪憸婊堝礈濮樿鲸宕叉繛鎴欏灩瀹告繃銇勯幘璺盒ョ€规洜鐏價tex
    """
    try:
        vertex_id = vertex_id.replace("%20", " ")
        database = require_database_access(database, user)
        result = delete_vertex(vertex_id, database)
        return {"success": True, "message": "Vertex deleted successfully"}
    except Exception as e:
        return {"success": False, "message": safe_str(e)}

@app.delete("/db/hyperedges/{hyperedge_id}")
async def delete_hyperedge_endpoint(hyperedge_id: str, database: str = None, user: dict = Depends(require_current_user)):
    """
    闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁嶉崟顒佹闂佺粯鍔曢顓犵不妤ｅ啯鐓冪憸婊堝礈濮樿鲸宕叉繛鎴欏灩瀹告繃銇勯幘璺盒涢柡浣告晲peredge
    """
    try:
        hyperedge_id = hyperedge_id.replace("%20", " ")
        vertices = hyperedge_id.split("|*|")
        database = require_database_access(database, user)
        result = delete_hyperedge(vertices, database)
        return {"success": True, "message": "Hyperedge deleted successfully"}
    except Exception as e:
        return {"success": False, "message": safe_str(e)}

# ========== 婵犵數濮烽弫鎼佸磻閻愬搫鍨傞柛顐ｆ礀缁犱即鏌熼梻纾嬵唹闁逞屽墾缁犳捇骞冨鍫熷殟闁靛鍎板Σ鎰版⒒娴ｅ憡璐￠柛搴涘€濆畷褰掑醇閺囩偤妫烽柣鐔哥懃鐎氼喚绮绘ィ鍐╁€垫繛鎴炵懕閸忣剟鏌ら弶鎸庡仴闁哄瞼鍠栭、娑橆潩椤掑绱戠紓鍌欑贰閸犳鎮烽埡浣烘殾鐟滅増甯╅弫濠囨煠濞村娅囬柍钘夌壗PI缂傚倸鍊搁崐鎼佸磹閻戣姤鍊块柨鏇炲€搁拑鐔兼煏婵犲繐顩い?==========

@app.get("/db/theme_hypergraph")
async def get_theme_hypergraph_endpoint(database: str = None, user: dict = Depends(require_current_user)):
    """Docstring."""
    try:
        database = require_database_access(database, user)
        data = get_theme_hypergraph(database)
        return data
    except Exception as e:
        return {"error": safe_str(e)}

@app.get("/db/theme_vertices")
async def get_theme_vertices_endpoint(database: str = None, page: int = None, page_size: int = None, user: dict = Depends(require_current_user)):
    """Docstring."""
    try:
        database = require_database_access(database, user)
        data = get_theme_vertices(database, page, page_size)
        return data
    except Exception as e:
        return {"error": safe_str(e)}

@app.get("/db/theme_hyperedges")
async def get_theme_hyperedges_endpoint(database: str = None, page: int = None, page_size: int = None, user: dict = Depends(require_current_user)):
    """Docstring."""
    try:
        database = require_database_access(database, user)
        data = get_theme_hyperedges(database, page, page_size)
        return data
    except Exception as e:
        return {"error": safe_str(e)}

@app.get("/db/theme_vertices_neighbor/{vertex_id}")
async def get_theme_vertex_neighbor_endpoint(vertex_id: str, database: str = None, user: dict = Depends(require_current_user)):
    """Docstring."""
    try:
        vertex_id = vertex_id.replace("%20", " ")
        database = require_database_access(database, user)
        data = get_theme_vertex_neighbor(vertex_id, database)
        return data
    except Exception as e:
        return {"error": safe_str(e)}

# 闂傚倸鍊峰ù鍥х暦閸偅鍙忕€规洖娲ㄩ惌鍡椕归敐鍫綈婵炲懐濮撮湁闁绘ê妯婇崕鎰版煕鐎ｅ吀閭柡灞剧洴閸╁嫰宕橀浣割潓闂備胶顭堟绋棵规搴㈩潟闁圭儤鏌￠崑鎾绘晲鎼存繄鏁栨繛瀵稿О閸ㄥ骞夐幖浣哥妞ゆ柨鐨烽弸鍛存⒑閸濆嫮鐒跨紓宥勭劍娣囧﹪骞栨担鑲濄劑鏌曟径娑橆洭闁哄棛鎸€I闂傚倸鍊搁崐宄懊归崶顒婄稏濠㈣泛顑囬々鎻捗归悩宸剰缁炬儳娼″鍫曞醇椤愵澀绨存繛?

class LLMProviderModel(BaseModel):
    name: str = ""
    baseUrl: str = ""
    modelName: str = ""
    apiKeys: List[str] = Field(default_factory=list)
    enabled: bool = True
    maxAsync: int = 1
    perKeyMaxAsync: Optional[int] = None
    priority: int = 100

class SettingsModel(BaseModel):
    apiKey: str = ""
    modelProvider: str = "openai"
    modelName: str = "gpt-5-mini"
    baseUrl: str = "https://api.openai.com/v1"
    selectedDatabase: str = ""
    maxTokens: int = 2000
    temperature: float = 0.7
    llmTimeout: float = 600
    llmModelMaxAsync: int = 16
    llmGlobalMaxAsync: int = 16
    llmPerKeyMaxAsync: int = 4
    llmMaxRetries: int = 1
    llmProviderStrategy: str = "priority_round_robin"
    llmProviders: List[LLMProviderModel] = Field(default_factory=list)
    # HyperRAG 闂傚倷娴囬褍顫濋敃鍌︾稏濠㈣埖鍔曠粻浼存煙闂傚鍔嶉柛銈嗗姈閵囧嫰寮介顫捕闂佹椿鍘介〃濠囧蓟濞戙垹鐒洪柛鎰剁細缁ㄧ敻姊虹紒妯烩拻闁告鍥ㄥ€剁€规洖娲犻崑鎾舵喆閸曨剛顦ュ┑鐐跺皺婵炩偓鐎规洘鍨块獮姗€骞栭鐔溠囨煙閸忚偐鏆橀柛銊ョ秺椤㈡挸鈽夐姀鈾€鎷洪梺鍛婄☉閿曘儳鈧灚鐟╅弻娑樷槈閸楃偞鐏撻梺?
    embeddingModel: str = "text-embedding-3-small"
    embeddingDim: int = 1536
    embeddingBaseUrl: str = ""  # 闂傚倷娴囬褍顫濋敃鍌︾稏濠㈣埖鍔曠粻浼存煙闂傚鍔嶉柛銈嗗姈閵囧嫰寮介顫捕闂佹椿鍘介〃濠囧蓟濞戙垹鐒洪柛鎰剁細缁ㄧ敻姊虹紒妯烩拻闁告鍥ㄥ€剁€规洖娲犻崑鎾舵喆閸曨剛顦ュ┑鐐跺皺婵炩偓鐎规洘鍨块獮妯肩磼濡　鍋撴繝姘厾闁诡厽甯掗崝姘舵煕閹垮啫寮慨濠冩そ瀹曘劍绻濋崒婊€妗撻梻浣哥－閹虫捇銆冮幒妤佲拻闁稿本鐟х粣鏃€绻涢悡搴吋婵﹣绮欏畷鐔碱敃椤愩倕鏁告繝纰樻閸垳鎷冮敃鍌涘€?
    embeddingApiKey: str = ""  # 闂傚倷娴囬褍顫濋敃鍌︾稏濠㈣埖鍔曠粻浼存煙闂傚鍔嶉柛銈嗗姈閵囧嫰寮介顫捕闂佹椿鍘介〃濠囧蓟濞戙垹鐒洪柛鎰剁細缁ㄧ敻姊虹紒妯烩拻闁告鍥ㄥ€剁€规洖娲犻崑鎾舵喆閸曨剛顦ュ┑鐐跺皺婵炩偓鐎规洘鍨块獮妯肩磼濡　鍋撴繝姘厾闁诡厽甯掗崝姘舵煕閹垮啫寮慨濠冩そ瀹曘劍绻濋崒婊€妗撻梻浣哥－閹虫捇銆冮幒妤佲拻濞达絿鐡旈崵娆撴⒑鐢喚鍒版い顓炴穿椤︽煡鎽堕悙瀵哥瘈闂傚牊渚楅崕蹇曠磼?
    # Cog-RAG闂傚倸鍊搁崐鐑芥嚄閸洖纾块柣銏㈩焾閻ょ偓绻濋棃娑卞剬闁逞屽墾缁犳挸鐣锋總绋课ㄩ柕澹懎骞€闂佽崵鍠愮划宀€鎹㈠鈧悰顔跨疀閺囨浜鹃柨婵嗛閺嬫稓绱掗埀顒勫醇閵忊€虫瀾闂婎偄娲︾粙鎴﹀礄?
    enableCogRAG: bool = True  # 闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁嶉崟顐ｇ€抽悗骞垮劚椤︻垰效?缂傚倸鍊搁崐鎼佸磹妞嬪海鐭嗗〒姘ｅ亾鐎规洘鍔欓幃婊堟嚍閵夈儲鐣遍梻浣稿閸嬪懎煤閺嶎厼鍑犲ù锝呯畭娴滄粓鏌曟径妯虹仯妞ゆ柨妾?RAG闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鍨鹃幇浣圭稁婵犵數濮甸懝鍓х玻濡ゅ懏鐓涢柛銉ｅ劚閻忊晝绱掗埀?
    # Hyper-RAG 婵犵數濮烽。钘壩ｉ崨鏉戠；闁告侗鍙庨悢鍡樹繆椤栨瑧绉挎繛鎴烆焸閺冨牆宸濇い鏃堟？缁ㄥ灚绻濋悽闈涗粶婵☆偅鐟╅獮鎰節濮橆厼浜楅梺閫炲苯澧撮柟顔筋殜閻涱噣宕归鐓庮潛婵犵數鍋涢惇浼村礉閹存繍鍤?
    hyperrag_domain: str = "default"  # "default", "flow_battery", or custom domains

class APITestModel(BaseModel):
    apiKey: str
    baseUrl: str
    modelName: str
    modelProvider: str

class DatabaseTestModel(BaseModel):
    database: str

@app.get("/settings")
async def get_settings(user: dict = Depends(require_current_user)):
    """
    闂傚倸鍊搁崐椋庣矆娓氣偓瀹曘儳鈧綆鍠栫壕鍧楁煙閹増顥夐幖鏉戯躬閺屻倝鎳濋幍顔肩墯婵炲瓨绮岀紞濠囧蓟濞戙垹唯闁靛繆鍓濋悵鏃堟煟鎼达紕浠涢柣鎿勭節瀵濡堕崱妯哄伎闂佸綊鍋婇崗姗€宕戦幘婢勬棃宕ㄩ鐔感氶梻浣虹帛椤洨鍒掗鐐茬；闁挎繂鎮胯ぐ鎺撴櫜闁搞儱澧庨崝鎼佹⒑閹惰姤鏁辨俊顐㈠暣瀵?
    """
    try:
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if not content:
                        main_logger.error("Log message")
                        return {
                            "success": False,
                            "message": "Settings file is empty"
                        }
                    settings = json.loads(content)
            except json.JSONDecodeError as e:
                main_logger.error("Log message")
                return {
                    "success": False,
                    "message": "Operation completed"
                }
            # 婵犵數濮烽弫鎼佸磻閻愬搫鍨傞柛顐ｆ礀缁犱即鏌涘┑鍕姢闁活厽鎸搁—鍐偓锝庝簻椤掋垻鈧娲橀悡锟犲蓟閻斿憡缍囬柛鎾楀懏娈搁梻浣虹帛閸旀洟鏁冮鍫濊摕闁挎繂顦粻娑欍亜閹烘垵鈧綊骞夐悡搴樻斀闁绘劕寮堕崳娲煟閳哄﹤鐏︾€殿喖顭烽幃銏ゆ偂鎼达綆鍚嬫俊鐐€栭弻銊╁触鐎ｎ喗鍊甸柣鎴烆焽缁犻箖鏌ㄥ┑鍡樺櫤闁瑰吋鍔欓弻銊╁即閵娿倝鍋楅梺缁樹緱閸犳绮欐径鎰闁?Key
            settings_safe = settings.copy()
            if 'apiKey' in settings_safe:
                settings_safe['apiKey'] = '***' if settings_safe['apiKey'] else ''
            if 'embeddingApiKey' in settings_safe:
                settings_safe['embeddingApiKey'] = mask_api_keys_for_settings(settings_safe.get('embeddingApiKey'))
            if isinstance(settings_safe.get('llmProviders'), list):
                safe_providers = []
                for provider in settings_safe.get('llmProviders', []):
                    if not isinstance(provider, dict):
                        continue
                    safe_provider = provider.copy()
                    keys = safe_provider.get('apiKeys') or []
                    if isinstance(keys, str):
                        keys = split_api_keys(keys)
                    safe_provider['apiKeys'] = ['***' for key in keys if key]
                    safe_providers.append(safe_provider)
                settings_safe['llmProviders'] = safe_providers
            settings_safe["is_admin"] = user.get("role") == "admin"
            if user.get("role") != "admin":
                settings_safe["apiKey"] = ""
                settings_safe["embeddingApiKey"] = ""
                settings_safe["llmProviders"] = []
            return settings_safe
        else:
            # 闂傚倸鍊风粈渚€骞栭位鍥敃閿曗偓閻ょ偓绻濇繝鍌滃闁藉啰鍠栭弻鏇熺箾閸喖澹勫┑鐐叉▕娴滄粓宕橀埀顒€顪冮妶搴″箺闁搞劏鍩栫粋鎺懳熺悰鈩冩杸闂佸疇妫勫Λ妤呮倶閵夛妇绠惧璺侯儐缁€瀣殽閻愯尙绠抽柍褜鍓ㄧ紞鍡涘窗閺嶎偆鐭嗛柛顐犲灪閸犳劙鐓崶銊р槈闁?
            return {
                "apiKey": "",
                "modelProvider": "openai",
                "modelName": "gpt-4o-mini",
                "baseUrl": "https://api.openai.com/v1",
                "selectedDatabase": "",
                "maxTokens": 2000,
                "temperature": 0.7,
                "llmTimeout": 600,
                "llmModelMaxAsync": 16,
                "llmGlobalMaxAsync": 16,
                "llmPerKeyMaxAsync": 4,
                "llmMaxRetries": 1,
                "llmProviderStrategy": "priority_round_robin",
                "llmProviders": [],
                "embeddingModel": "text-embedding-3-small",
                "embeddingDim": 1536,
                "embeddingBaseUrl": "",
                "embeddingApiKey": ""
            }
    except Exception as e:
        return {"success": False, "message": safe_str(e)}

@app.post("/settings")
async def save_settings(settings: SettingsModel, user: dict = Depends(require_admin_user)):
    """
    婵犵數濮烽弫鎼佸磿閹寸姴绶ら柦妯侯棦濞差亝鏅滈柣鎰靛墮鎼村﹪姊虹粙璺ㄧ伇闁稿鍋ゅ畷鎴﹀Χ婢跺鍘繝鐢靛€崘銊︽濡炪倖娉﹂崶銊㈡嫼闂佺粯鎸哥€垫帒顭囬悢鍏肩厱濠电姴鍠氬▓婊呪偓瑙勬礃濡炰粙骞冮埡鍐＜婵☆垵妗ㄩ崠鏍р攽閻愯埖褰х紒鎻掓健閳ワ箓宕奸妷銉у幈闂佸搫鍟悧濠囨偂?
    """
    try:
        settings_dict = settings.dict()
        existing_settings = {}
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                    existing_settings = json.load(f)
            except Exception:
                existing_settings = {}

        # 濠电姷鏁告慨鐑藉极閹间礁纾块柟瀵稿Х缁€濠囨煃瑜滈崜姘跺Φ閸曨垰鍗抽柛鈩冾殔椤忣亪鏌涘▎蹇曠闁哄矉缍侀獮鍥敆閸屾瑧椹抽梺璇插閸戝綊宕滈悢鐓庤摕婵炴垯鍨圭粻娑㈡⒒閸喓鈽夌紒鐘侯嚙閳规垿鍨鹃崘鑼獓闂佽鍠栭崐鍨嚕婵犳碍鏅搁柣妯垮皺椤︺劑姊洪幐搴㈢５闁稿鎹囬弻娑㈠籍閳ь剙顫濋妸褎顫?
        main_logger.info(
            f"濠电姷顣藉Σ鍛村磻閹捐泛绶ゅù鐘差儏閻ゎ喗銇勯弽顐粶闁?[Settings] 闂傚倸鍊搁崐宄懊归崶顒婄稏濠㈣泛顑囬々鎻捗归悩宸剰缁炬儳娼￠弻锛勪沪鐠囨彃濮庨梺鍝勵儎閼冲爼骞夐幖浣瑰亱闁割偅绻勯悷銊х磽娴ｆ彃浜鹃梺绯曞墲缁嬫帡鎮″▎鎰闁割偅绻勬禒銏ゆ煛鐎ｎ剙鏋涢柡宀嬬秮閺佹劖寰勬径瀣灓闂備浇顕栭崰娑綖婢舵劕绠柛娑卞灣閻瑩骞栫€涙ɑ灏伴悗鍨墵濮? "
            f"{json.dumps(redact_for_log(settings_dict), ensure_ascii=False, indent=2)}"
        )

        # 婵犵數濮烽弫鍛婃叏閻戝鈧倹绂掔€ｎ亞鍔﹀銈嗗坊閸嬫捇鏌涢悢閿嬪仴闁糕斁鍋撳銈嗗坊閸嬫挾绱撳鍜冭含妤犵偛鍟灒闁煎鍊楅悾钘夘渻閵堝簼绨芥い顐㈢翱ey闂?**闂傚倸鍊搁崐鐑芥倿閿旈敮鍋撶粭娑樻噽閻瑩鏌熸潏楣冩闁搞倖鍔栭妵鍕冀椤愵澀绮堕梺鎼炲妼閸婂綊濡甸崟顖氬唨闁靛ě浣插亾閹烘鐓冮柣鐔稿鏍＄紓浣虹帛缁诲牆螞閸愩劉妲堟繛鍡樺姈閸婄兘姊绘担椋庝覆閻庨潧鐭傚畷鎶芥晲婢跺﹨鎽曞┑鐐村灦椤倿鎮㈤崗鐓庝簵闁瑰吋鐣崹濠氬焵椤掍礁鍔ら柍瑙勫灴閹晠顢曢～顓烆棜婵犵數鍋為幐濠氬春閸愵喖纾婚柟鍓х帛閻撴瑦銇勯弽銊ㄥ闁哄棴绲块埀顒冾潐濞叉ê鐣濋幖浣哥畺闁绘劖浜介埀顒€鍊搁娆忣潖閺呭﹤鈹戦悩鍨毄闁稿鍋ゅ畷褰掑醇閺囩偟顔囬梺鍛婄缚閸庢娊鎯岄幘鍓佹／闁诡垎灞藉壄婵?
        if settings_dict.get('apiKey') == '***':
            # 闂傚倸鍊峰ù鍥х暦閸偅鍙忛柡澶嬪殮濞差亜鐓涢柛婊€鐒﹂弲顏堟偡濠婂嫬鐏村┑锛勬暬楠炲洭寮剁捄銊モ偓鐐差渻閵堝棗绗傜紒鈧担鍦浄闁靛繈鍊栭埛鎴犵磽娴ｇ櫢渚涙繛鍫熸閺岋絽螖閳ь剟鏁冮敂鎯у灊濠电姵鑹剧粻铏繆閵堝嫮顦﹀ù鐙€鍨辩换娑欐綇閸撗勫仹濡炪値鍘奸悧鎾诲春濞戙垹绫嶉柛顐ゅ枔閸樹粙姊洪棃娑氬闁瑰啿绻樿棢闁绘劗鏁哥壕濂告倵閿濆簼鎲炬俊鍙夋倐閺屽秶绱掑Ο璇茬３濡ょ姷鍋涢悧蹇撯槈閻㈢纾介柣娑氱y
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                    existing_settings = json.load(f)
                # 婵犵數濮烽弫鎼佸磿閹寸姴绶ら柦妯侯棦濞差亝鏅滈柣鎰靛墮鎼村﹪姊洪崨濠傚Е濞存粍鐗犲畷鎴﹀箻鐠囨彃鐎銈嗗姧缂嶅棗螞閸愵喗鍊甸悷娆忓绾炬悂鏌涢妸銈囩煓妤犵偛鍟存慨鈧柕鍫濇噹缁愭稒绻濋悽闈浶㈤悗姘煎櫍瀵娊濮€閵堝棌鎷绘繛杈剧到濠€鍗烇耿娴犲鐓曢柡鍌濇硶閻掑摜鈧娲栧﹢杈╁垝濮橆剦娼伴柕鏇炲潖y
                settings_dict['apiKey'] = existing_settings.get('apiKey', '')
            else:
                # 婵犵數濮烽弫鍛婃叏閻戝鈧倹绂掔€ｎ亞鍔﹀銈嗗坊閸嬫捇鏌涢悢閿嬪仴闁糕斁鍋撳銈嗗坊閸嬫挾绱撳鍜冭含妤犵偛鍟灒閻犲洩灏欑粣鐐寸節閻㈤潧浠ч柛瀣崌閹繝濮€閵堝棌鎷洪梺鍝勫€堕崕鎻掆枍閸涘瓨鐓曢柣鏇氱閻忥絿绱掗纰辩吋妤犵偞甯掕灃濞达絽鎼獮妤佺節閻㈤潧孝闁挎洏鍊濋獮濠冩償閵婏絺鍋撻崒鐐茬闁兼祴鏅濋惁鍫ユ⒑闁偛鑻晶顖炴煙瀹勭増鍤囬柟顔界矊铻ｅ〒姘煎灙閸嬫挸鈽夐姀鈾€鎷洪梺鍛婄☉閿曘儳鈧灚鐟╅弻娑樷槈閸楃偞鐏撻梺閫炲苯澧婚柛娆忓暙椤繐煤椤忓嫪绱堕梺鍛婃处閸嬧偓闁稿鎸剧划娆徫涢崹顐ｃ仢闁轰焦鍔欏畷銊╊敂閸涱垪鍋撴繝姘拺闂傚牊绋撶粻鐐烘煕婵犲啰澧电€殿喗鐓￠、妤呭礋椤掆偓閳ь剙鐖奸弻锝夊箛椤栨氨鍘銈冨劚椤︾敻寮婚敐鍫㈢杸闁哄洨鍋為悘鍫ユ⒑鐠団€虫灕妞ゎ偄顦甸獮蹇涘川椤栨粎鐓撻柣鐘充航閸斿酣鍩ｉ妶澶嬧拺闁煎鍊曟牎闂佸憡姊归〃濠傜暦娴兼潙绠婚悹鍝勬惈閻忓﹤鈹戦绛嬬劸婵炲绋掔€靛ジ鎮╃紒妯煎幈闂佸搫娲㈤崝宀勭嵁濡ゅ懏鐓欓柤鑹版硾閸氬湱绱掓潏銊﹀鞍闁瑰嘲鎳愰幏鐘诲焺閸愭儳鎮堢紓鍌氬€搁崐鎼佸磹閻熼偊娼╅柕濞炬櫅缁?
                settings_dict['apiKey'] = ''

        # embeddingApiKey supports multiple keys separated by newline/comma/semicolon.
        # Preserve masked rows returned by GET /settings while allowing users to add/remove keys.
        settings_dict['embeddingApiKey'] = resolve_masked_api_key_text(
            settings_dict.get('embeddingApiKey'),
            existing_settings.get('embeddingApiKey', ''),
        )

        # 缂傚倸鍊搁崐鐑芥嚄閸洘鎯為幖娣妼閸屻劑鏌涢幘妤€鎳嶇粭澶岀磽娴ｇ绾х紒妤侇暥edding闂傚倸鍊搁崐鐑芥嚄閸洖纾块柣銏㈩焾閻ょ偓绻濋棃娑卞剬闁逞屽墾缁犳挸鐣锋總绋课ㄩ柕澹懎骞€闂佽崵鍠愮划宀€鎹㈠鈧畷娲焵椤掍降浜滈柟鍝勭Х閸忓矂鏌嶉娑欑闁靛洤瀚版俊鎼佸Ψ閿旂粯锛嗛梻浣筋嚃閸犳稑鈻斿☉顫稏婵犻潧娲︾紞鍥煃閸濆嫸宸ラ柡鍜佸墴濮?
        if 'embeddingBaseUrl' not in settings_dict:
            settings_dict['embeddingBaseUrl'] = ''

        existing_providers = existing_settings.get('llmProviders') or []
        if isinstance(settings_dict.get('llmProviders'), list):
            resolved_providers = []
            for provider_index, provider in enumerate(settings_dict.get('llmProviders', [])):
                if not isinstance(provider, dict):
                    continue
                existing_provider = None
                for old_provider in existing_providers:
                    if not isinstance(old_provider, dict):
                        continue
                    if (
                        old_provider.get('name') == provider.get('name')
                        and old_provider.get('baseUrl') == provider.get('baseUrl')
                        and old_provider.get('modelName') == provider.get('modelName')
                    ):
                        existing_provider = old_provider
                        break
                if existing_provider is None and provider_index < len(existing_providers):
                    existing_provider = existing_providers[provider_index]

                existing_keys = []
                if isinstance(existing_provider, dict):
                    existing_keys = existing_provider.get('apiKeys') or []
                    if isinstance(existing_keys, str):
                        existing_keys = split_api_keys(existing_keys)

                new_keys = provider.get('apiKeys') or []
                if isinstance(new_keys, str):
                    new_keys = split_api_keys(new_keys)
                resolved_keys = []
                for key_index, key in enumerate(new_keys):
                    key_text = safe_str(key).strip()
                    if key_text == '***':
                        if key_index < len(existing_keys):
                            resolved_keys.append(existing_keys[key_index])
                    elif key_text:
                        resolved_keys.append(key_text)
                provider['apiKeys'] = resolved_keys
                resolved_providers.append(provider)
            settings_dict['llmProviders'] = resolved_providers
            reset_llm_provider_pool_health()

        main_logger.info(
            f"濠电姷顣藉Σ鍛村磻閹捐泛绶ゅù鐘差儏閻ゎ喗銇勯弽銊︾殤闁?[Settings] 闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁撻悩鎻掔€梻鍌氱墛閸忔艾鈽夊Ο婊勬閸┾偓妞ゆ帒鍟徊褰掓⒒娴ｈ鍋犻柛搴灦瀹曟繃鎯旈敐鍥︾瑝闂佺懓澧界划顖炴偂閻旂厧绠抽柟鎯版缁€澶愭煙鏉堝墽鐣辩紒鐘冲哺閺屾盯骞囬棃娑欑亪缂備讲鍋撻悗锝庡亖娴滄粓鏌￠崒姘变虎闁抽攱姊婚惀? "
            f"{json.dumps(redact_for_log(settings_dict), ensure_ascii=False, indent=2)}"
        )

        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings_dict, f, ensure_ascii=False, indent=2)
        return {"success": True, "message": "Operation completed"}
    except Exception as e:
        main_logger.error("Log message")
        return {"success": False, "message": safe_str(e)}

@app.get("/llm-provider-pool/status")
async def get_llm_provider_pool_status(user: dict = Depends(require_admin_user)):
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            settings = json.load(f)
        return {"success": True, "data": summarize_llm_provider_pool(settings)}
    except Exception as e:
        return {"success": False, "message": safe_str(e)}

@app.post("/llm-provider-pool/reset")
async def reset_llm_provider_pool_status(user: dict = Depends(require_admin_user)):
    try:
        reset_llm_provider_pool_health()
        return {"success": True, "message": "LLM provider pool health reset"}
    except Exception as e:
        return {"success": False, "message": safe_str(e)}

@app.get("/domains")
async def get_domains():
    """Docstring."""
    try:
        from hyperrag.domains.domain_manager import domain_manager
        domains = domain_manager.get_available_domains()
        result = []
        for domain_name in domains:
            try:
                config = domain_manager.load_domain_config(domain_name)
                result.append({
                    "name": domain_name,
                    "description": config.get("domain_description", ""),
                    "output_format": config.get("output_format", "delimiter"),
                })
            except Exception:
                result.append({
                    "name": domain_name,
                    "description": "",
                    "output_format": "delimiter",
                })
        return {"domains": result}
    except Exception as e:
        main_logger.error("Log message")
        return {"domains": [{"name": "default", "description": "Default domain", "output_format": "delimiter"}]}

@app.get("/databases")
async def get_databases(user: dict = Depends(require_current_user)):
    """
    闂傚倸鍊搁崐椋庣矆娓氣偓瀹曘儳鈧綆鍠栫壕鍧楁煙閹増顥夐幖鏉戯躬閺屻倝鎳濋幍顔肩墯婵炲瓨绮岀紞濠囧蓟濞戙垹唯妞ゆ梻鍘ч～鈺呮⒑濞茶骞楁い銊ワ躬瀵鍩勯崘鈺侇€撻梻鍌氱墛缁嬪牓宕戦幘鏂ユ斀闁糕檧鏅涘▓銊ヮ渻閵堝棗濮ч梻鍕瀹曟垹鈧綆鍠楅悡鏇熴亜閹板墎鎮肩紒鐘筹耿閺屾洟宕奸鍌滄殼闂佸搫鐬奸崰鏍箖閳╁啯鍎熼柨婵嗘閸犳牠姊绘担鐑樺殌闁硅绻濋獮鍐磼濮樿鲸娈鹃悷婊呭鐢晠寮崒鐐寸厱闁斥晛鍘鹃鍛浄?
    """
    try:
        databases = []

        # 婵犵數濮烽弫鎼佸磻閻樿绠垫い蹇撴缁€濠囨煃瑜滈崜姘辨崲濞戞瑥绶為悗锝庡亞椤︿即鎮楀▓鍨珮闁稿锕ㄥΛ鐔哥節闂堟稑鈧鎮楃粚鏈糿ager闂傚倸鍊搁崐椋庣矆娓氣偓瀹曘儳鈧綆鍠栫壕鍧楁煙閹増顥夐幖鏉戯躬閺屻倝鎳濋幍顔肩墯婵炲瓨绮岀紞濠囧蓟濞戙垹唯妞ゆ梻鍘ч～鈺呮⒑閸濆嫷鍎庣紒鑸靛哺瀵鏁愰崨鍌涙閸┾偓妞ゆ帒瀚崑瀣煕閳╁啰鎳呴柣顓炵墦閺屻劑寮撮悙娴嬪亾閸濄儳涓嶇憸鐗堝笚閸婂灚绻涢幋鐑嗕紗闁瑰濮抽悞濠冦亜閹惧崬鐏柣鎾存礃閵囧嫰顢橀悢椋庝化缂備降鍔嬬划娆撳蓟?
        database_files = db_manager.list_databases()

        for db_info in database_files:
            # db_info 闂傚倸鍊搁崐鐑芥嚄閸撲礁鍨濇い鏍ㄧ矊閸ㄦ繄鈧箍鍎遍幏瀣偄閸℃ü绻嗘い鏍ㄧ矊閻ㄦ垿鏌ら悧鍫濐嚋闁靛洤瀚粻娑㈠箻鐠轰警鏆梻浣告啞閻熴儵鏁冮鍫濊摕闁挎繂顦悡鈧┑鐐叉缁绘垿骞栭幇顔剧＜闁逞屽墴瀹曟帡鎮欑€电骞堟繝鐢靛仦閸ㄥ爼鏁冮锕€绀夐柣鏂款殠閻斿棝鎮峰▎蹇擃仼濠殿喖顦甸弻宥堫檨闁告挻宀搁、娆撳冀椤撶偟鐛ラ梺鍝勭▉閻撳牆鈻撴禒瀣彄闁搞儯鍔嶇粈鍐┿亜椤愶絾绀冪紒缁樼箞濡啫鈽夐崡鐐插缂傚倷璁查崑鎾垛偓鍏夊亾闁告洦鍓涢崢鍗炩攽閻愭潙鐏ョ€规洦鍓熼悰顔嘉旈崨顔惧幈?'name', 'description', 'system' 闂傚倸鍊峰ù鍥敋瑜忛埀顒佺▓閺呮繄鍒掑▎鎾崇婵＄偛鐨烽崑?
            if isinstance(db_info, dict):
                databases.append(db_info)
            else:
                # 闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁嶉崟顐ｇ€抽悗骞垮劚椤︻垶宕归崒鐐寸厽闁靛繈鍩勯悞鍓х磼閻樺磭澧ǎ鍥э躬婵″爼宕ㄩ鍏碱仩缂傚倷璁查崑鎾绘煕瀹€鈧崑鐐烘偂閻斿吋鐓欓柣鎰靛墮閳绘洟鏌涘▎蹇擃伃闁哄备鍓濋幏鍛村传閵夋劑鍨洪妵鍕敃閿濆洨鐤勫銈冨灪椤ㄥ﹤鐣烽悢纰辨晝闁靛繒濮甸璇测攽閻樺灚鏆╁┑顔芥尦閺佸啴濡堕崶锝呬壕婵鍘ч獮姗€鏌ｉ悢婵嗘处閳锋帒霉閿濆懏鍟為柟顖氱墦閺屾盯鎮欑€电寮ㄩ悗瑙勬礈閸犳牠銆佸鈧幃婊堝幢濮楀棙顥犻梻鍌欐祰椤曆呪偓娑掓櫊椤㈡瑩寮介鐐电崶闂佸搫绋侀悡鍫濃枔娴犲鍙撻柛銉ｅ妽缁€鍐┿亜椤愶絾绀冪紒缁樼洴瀹曞崬螣閾忛€涙喚闂備胶顭堥鍡涘箰閹间礁鐓″璺号堥弸搴繆椤栨繂鍚归柡鍡╁幗缁绘繈鎮介棃娑楁勃闂佹悶鍔岄悥濂哥嵁閹寸偟鐟归柍褜鍓熼妴浣割潩椤掑鍙嗛梺鍛婁緱閸ｎ喖顭囬悢灏佹斀妞ゆ梻鐡旈悞楣冩煕閳哄倻澧电€殿喗鐓￠、妤呭礋椤掆偓閳ь剙鐖奸弻锝夊箛椤栨氨鍘銈冨劚椤︾敻寮婚敐鍫㈢杸闁哄洨鍋為悘鍫ユ倵濞堝灝鏋涢柣鏍с偢楠炲啫鈻庨幘宕囶唽闂佸湱鍎ら弻銊╁箹閸涘﹦绡€闁汇垽娼ф禒锕傛煕閵娿儳鍩ｆ鐐村姍楠炴牗鎷呴崫銉晣婵＄偑鍊栭崝褔姊介崟顖氱；闁靛牆娲﹂崰鎰版煛閸屾繃纭堕柡?
                databases.append({
                    "name": db_info,
                    "description": f"{db_info.replace('.hgdb', '')} database",
                    "system": "hyperrag"  # 婵犵數濮甸鏍窗濡ゅ啯鏆滄俊銈呭暟閻瑩鏌熼悜妯镐粶闁逞屽墾缁犳挸鐣烽悡搴樻斀闁告劏鏅╁?HyperRAG
                })

        # 婵犵數濮烽弫鍛婃叏閻戝鈧倹绂掔€ｎ亞鍔﹀銈嗗坊閸嬫捇鏌涢悢閿嬪仴闁糕斁鍋撳銈嗗坊閸嬫挾绱撳鍜冭含妤犵偛鍟灒閻犲洩灏欑粣鐐寸節閻㈤潧浠ч柛瀣崌閹繝濮€閵堝棌鎷洪梺鍝勫€堕崕鎻掆枍閸涘瓨鐓曢柣鏇氱閻忥絿绱掗纰辩吋妤犵偞甯掕灃濞达絽鎼獮宥夋⒒娴ｇ顥忛柣鎾崇墦瀹曟垿宕熼姘鳖槷闂侀潧鐗嗛ˇ浼存偂閺囥垺鐓冮弶鐐村閸忓矂鏌ｉ幒鎴炴喐闁逞屽墯椤旀牠宕抽鈧畷鎴炵節閸パ呯暫閻熸粍鏌ㄩ悾鐑芥偂鎼存ɑ鏂€闂佸壊鍋呯粙鎴炵娴煎瓨鈷掑ù锝呮啞鐠愶繝鏌涘Ο鐘叉处閸嬨倝鏌曟繛鐐珔缂佺姵婢橀埞鎴︽偐鐎圭姴顥濋梺鍛婂灩婵炩偓闁哄本鐩獮鍥Ω閿旂晫褰囨俊鐐€愰弲婵嬪礂濮椻偓楠炲啰鎲撮崟顒€顎撻梺鍛婄☉閿曘劎娑甸埀顒傜磽閸屾瑨顔夐柛瀣尭椤潡鎳滈棃娑橆潓缂備胶瀚忛崶銊у帗闂佸憡绻傜€氼剟鍩€椤掆偓缂嶅﹪骞冮敓鐘参ㄩ柨鏂垮⒔椤旀洟姊洪崨濠勬噧妞わ箒椴搁弲鍫曨敆娴ｅ吀绨诲銈呯箣缁€浣圭閻愵剛绡€缁剧増蓱椤﹪鏌涢妸锔界凡妞ゎ厼娲崹鎯х暦閸ャ劍顔曟繝娈垮枟閿曗晠宕曢悽绋跨睄闁割偅绻勯ˇ浼存⒑鐎圭媭娼愰柛搴ゆ珪缁?
        databases = [
            {**db, "display_name": database_display_name(db.get("name", ""), user)}
            for db in databases
            if user_can_access_database(user, db.get("name"), include_legacy=True)
        ]

        if not databases:
            databases = []

        return databases
    except Exception as e:
        return {"success": False, "message": safe_str(e), "data": []}

@app.post("/test/embedding")
async def test_embedding(user: dict = Depends(require_current_user)):
    """
    濠电姷鏁告慨鐑藉极閹间礁纾婚柣鎰▕閻掕姤绻涢崱妯绘儎闁轰礁瀚伴弻娑㈩敃閻樻彃濮曢梺绋块閿曘儵濡甸崟顖氬唨闁靛濡囧▓銈夋⒑閸濆嫭顥撻柛濠冪箞楠炲啫顫滈埀顒勫箖濞嗘挻鍤嬫繛鍫熷椤ュ鏌ｆ惔銏╁晱闁哥姵宀搁幃锟犅ㄩ張鎾绘⒒閸屾瑧顦﹂柟纰卞亰钘濇い鎰剁畱閻ょ偓绻濋棃娑卞剰缁炬儳顭烽弻锝夊箛椤掑倷绮甸梺?
    """
    try:
        main_logger.info("Log message")

        # 婵犵數濮烽弫鎼佸磻濞戙埄鏁嬫い鎾跺枑閸欏繘鏌℃径瀣劸婵炲皷鏅犻弻銊╁棘閸喒鎸冪紒鎯у綖缁瑩寮诲☉銏犵疀闁靛闄勯悵鏍⒑闁偛鑻晶濠氭煕閻樺磭澧垫繝鈧笟鈧铏圭磼濡浚浜畷顖炲锤濡も偓缁€澶愭煕椤愶絾绀冮柍閿嬪灴閺屾稑鈽夊鍫濆闂佺懓鍟跨€氫即寮婚敐鍛傛棃宕橀妸銏＄€伴柣搴ゎ潐濞插繘宕归懞銉ょ箚闁割偅娲栭悙濠囨煃閸濆嫬鏋︾紒?
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            settings = json.load(f)

        embedding_model = settings.get("embeddingModel", "text-embedding-3-small")
        api_key = settings.get("embeddingApiKey", settings.get("apiKey"))
        base_url = settings.get("embeddingBaseUrl", settings.get("baseUrl"))
        user_embedding_provider = auth_store.get_enabled_provider(user["id"], "embedding")
        if user_embedding_provider:
            embedding_model = user_embedding_provider["modelName"]
            api_key = user_embedding_provider["apiKey"]
            base_url = user_embedding_provider["baseUrl"]
            key_candidates = get_api_key_candidates(f"embedding:user:{user['id']}", api_key)
        else:
            key_candidates = get_api_key_candidates("embedding", api_key, settings.get("apiKey"))

        main_logger.info(
            f"濠电姷鏁告慨鐑藉极閹间礁纾婚柣鎰▕閻掕姤绻涢崱妯绘儎闁轰礁瀚伴弻娑㈩敃閻樻彃濮曢梺绋块閿曘儵濡甸崟顖氬唨闁靛濡囧▓銈夋⒑閸濆嫭顥撻柛濠冪箞楠炲啫顫滈埀顒勫箖濞嗘挻鍤嬫繛鍫熷椤ュ鏌ｆ惔銏╁晱闁哥姵绋戦埢宥夊即閻旇　鏀虫繝鐢靛Т濞村倿寮鍡曠箚闁绘劙顤傞崵娆徝瑰鍐ㄢ挃闁逞屽墲椤煤閺嶎灐娲偐鐠囪尙锛? {embedding_model}, "
            f"Embedding Key濠? {summarize_key_pool('embedding', api_key, settings.get('apiKey'))}"
        )

        # 婵犵數濮烽弫鎼佸磻閻樿绠垫い蹇撴缁€濠囨煃瑜滈崜姘辨崲濞戞瑥绶為悗锝庡亞椤︿即鎮楀▓鍨珮闁稿锕ユ穱濠囧醇閺囩偟鍊為梺瀹犮€€閸嬫挾绱掑Δ鈧ˇ闈涱潖濞差亝鐒婚柣鎰蔼鐎氭澘顭胯椤曨參鍩€椤掑喚娼愭繛娴嬫櫇閹广垹鈹戦崱鈺佹闂佸湱铏庨崰妤呭磻閹邦喒鍋撶憴鍕婵炶绠戦埢鎾诲川婵犲嫮鐦堥梺姹囧灲濞佳勭閿旂晫绠鹃柛蹇氬亹閹冲洦銇勯姀锛勫⒌鐎规洖銈告俊鐑芥晝閳ь剟宕滈妸銉富闁靛牆妫涙晶閬嶆煕鐎ｎ偆鈽夐摶鐐存叏濡炶浜鹃梺鍝勬湰閻╊垱淇婇悜鑺ユ櫜闁告侗鍙庨悗鎾⒒?
        test_texts = ["This is a test for embedding API connectivity."]

        if not key_candidates:
            key_candidates = [(0, 0, None)]

        embeddings = None
        errors = []
        for key_index, key_total, candidate_key in key_candidates:
            try:
                if candidate_key:
                    main_logger.info("Log message")
                embeddings = await openai_embedding(
                    test_texts,
                    model=embedding_model,
                    api_key=candidate_key,
                    base_url=base_url,
                )
                break
            except Exception as e:
                detailed_error = extract_detailed_exception_message(e)
                errors.append(detailed_error)
                if candidate_key:
                    mark_api_key_unhealthy("embedding", candidate_key, detailed_error)
                main_logger.error(
                    f"Embedding濠电姷鏁告慨鐑藉极閹间礁纾婚柣鎰▕閻掕姤绻涢崱妯绘儎闁轰礁瀚伴弻娑㈩敃閻樻彃濮曢梺绋块閿曨亪寮婚敐澶娢ч柛鈩冪懐娴兼潾闂傚倸鍊搁崐鐑芥嚄閸洍鈧箓宕奸妷锔芥珖闂侀潧顦弲婊堝磻閿熺姵鐓冮柛婵嗗閸ｅ綊鏌ｉ幒鎴犱粵闁靛洤瀚伴獮鎺楀幢濡炴儳顥氬┑锛勫亼閸娧呪偓闈涚焸瀹曞綊鎳滈崗鍝ョ畾闂佹眹鍨婚…鍫㈢不閿濆鐓熸俊顖氭惈閺嗚鲸銇? {key_index}/{key_total}, 闂傚倸鍊搁崐鎼佸磹閻戣姤鍊块柨鏃堟暜閸嬫挾绮☉妯诲闁? {detailed_error}"
                )
        if embeddings is None:
            raise RuntimeError("All embedding API keys failed: " + " || ".join(errors))

        return {
            "success": True,
            "message": "Operation completed",
            "details": {
                "model": embedding_model,
                "embedding_dim": embeddings.shape[1] if len(embeddings.shape) > 1 else embeddings.shape[0],
                "test_text_length": len(test_texts[0])
            }
        }
    except Exception as e:
        error_msg = log_detailed_exception(
            main_logger,
            "Embedding API test failed",
            e,
            {
                "embedding_model": locals().get("embedding_model"),
                "embedding_base_url": locals().get("base_url"),
                "test_text_count": 1,
                "test_text_total_chars": len(test_texts[0]) if "test_texts" in locals() else None,
            },
        )

        # 闂傚倸鍊搁崐椋庣矆娴ｉ潻鑰块弶鍫氭櫅閸ㄦ繃銇勯弽顐粶缂佲偓婢舵劖鐓欓柣鎴炆戦埛鎰亜閹邦亞鐭欓柡宀嬬秮婵偓闁绘ê鍟块弳鍫ユ⒑缁嬫鍎嶉柛鏃€鍨垮濠氬即閻旇櫣鐦堥棅顐㈡处濞叉粓寮抽悩缁樷拺缂備焦蓱鐏忕増绻涢懠顒€鏋涚€殿喛顕ч埥澶娢熼柨瀣偓濠氭椤愩垺绁紒韫矙瀹曟粍瀵肩€涙ǚ鎷洪梻鍌氱墛缁嬫挻鏅堕弮鍌滅＜妞ゆ梻鏅幊鍥殽閻愬弶顥㈢€规洘锕㈤、娆撴嚃閳哄﹥效濠碉紕鍋戦崐鏍偋濡ゅ啰鐭欓柟鐑樺灍閺嬪秹鏌熼崜褏甯涢柣鎾跺枛閺岋絽螣閸濆嫮楠囬梺娲诲幗椤ㄥ牏妲愰幒鏃€瀚氶柛娆忣樈濡箓姊?        user_friendly_error = extract_user_friendly_error(error_msg)

        return {
            "success": False,
            "message": user_friendly_error,
            "detailed_error": error_msg[:500]
        }

@app.post("/test-api")
async def test_api_connection(api_test: APITestModel, user: dict = Depends(require_current_user)):
    """
    濠电姷鏁告慨鐑藉极閹间礁纾婚柣鎰▕閻掕姤绻涢崱妯绘儎闁轰礁瀚伴弻娑㈩敃閻樻彃濮曢梺绋块閿曨亪寮婚敐澶娢ч柛婊€鐒﹂弲顢梻鍌氬€风粈渚€骞栭位鍥敃閿曗偓閻ょ偓绻濋棃娑卞剰缁炬儳顭烽弻锝夊箛椤掑倷绮甸梺?
    """
    try:
        from openai import OpenAI
        
        # 闂傚倸鍊搁崐椋庣矆娓氣偓楠炴牠顢曢妶鍥╃厠闂佺粯鍨堕弸鑽ょ礊閺嵮岀唵閻犺櫣灏ㄩ崝鐔兼煛閸℃劕鈧洟婀侀梺鎸庣箓閹冲繒鎷归敓鐘崇厓缂備焦蓱閳锋帡鏌嶈閸撴瑧绮诲澶婄？闂侇剙绉寸粻鐘荤叓閸ャ劎鈽夌痪鎯х秺濮婃椽顢楅埀顒傜矓閻㈠憡鍋傞柣鏂垮悑閻撳繐鈹戦悙鑼虎闁告梹纰嶉妵鍕疀閿濆嫰鍋楅梺纭呮珪瀹€鎼佸春閿熺姴宸濇い鏃€鍎抽獮鍫ユ⒒娓氣偓濞佳団€﹂崼銉ョ？婵炲樊浜滅壕鍧楁煙闁箑鏋熼柛鐘冲姇铻炲Λ棰佹祰閸忓矂鏌涢弬璺ㄐょ紒杈ㄥ笒铻栭柛鎰╁妽閻庡姊虹€圭姵顥夋い锔诲灥閻忔帞绱撻崒娆戝妽妞ゎ厼娲╅妵鎰吋婢跺鎷洪梺鍛婄箓鐎氬嘲危閹绢喗鐓涢柛娑卞枤閻瞼绱掗鐣屾噰鐎殿喕绮欐俊姝岊槾妞ゆ梹娲熷娲传閸曞灚效闂佺硶鏅涢悧鎾崇暦閺囥垹绠荤紓浣诡焽閸?
        if api_test.modelProvider == "openai":
            client = OpenAI(
                api_key=api_test.apiKey,
                base_url=api_test.baseUrl
            )
            
            # 闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁撻悩鍐蹭画闂佹寧娲栭崐鎼佸垂閸岀偞鐓曠憸搴ㄣ€冮崨瀛樺€块柛顭戝亖娴滄粓鏌熺€电浠滄い鏇熺矋閵囧嫰鏁冮崒銈嗩棖缂備浇椴哥敮鈥愁嚕椤掑倹宕夐柕濠忛檮閸犳牜绱撻崒娆戭槮妞ゆ垵鎳樿棟闁汇垻顭堢粻鏍煙椤栧棌鍋撻柡鈧禒瀣€甸柨婵嗙凹缁ㄨ姤銇勯姀鐘冲殗婵﹥妞藉畷顐﹀礋椤掆偓缁愭稒绻濆▓鍨灓闁轰礁顭烽獮鍐倷椤掍胶绉堕梺闈浤涢崪浣告櫗闂傚倷绀侀幖顐λ囨导鏉戞槬闁割偁鍎辩壕鍧楁煙閸撗呭笡闁绘挾鍠栭弻銊╁籍閸ヨ泛娈梺璇查獜缂嶄線寮婚悢鍓叉Ч閹肩补妾ч弸鍛存⒑閸濆嫯顫﹂柛鏂块叄閸┾偓妞ゆ帒锕︾粔鐢告煕閹炬潙鍝虹€?
            response = client.chat.completions.create(
                model=api_test.modelName,
                messages=[{"role": "user", "content": "Hello"}],
                max_tokens=10
            )
            
            return {"success": True, "message": "Operation completed"}
            
        elif api_test.modelProvider == "anthropic":
            # 闂傚倸鍊峰ù鍥敋瑜嶉湁闁绘垼妫勯弸浣糕攽閻樺疇澹橀柣鎺戠仛閵囧嫰骞掑鍫濆帯闂侀潧妫欑敮锟犲蓟閵堝鎹舵い鎾跺О閳ь剚濮hropic闂傚倸鍊搁崐鐑芥倿閿旈敮鍋撶粭娑樻噽閻瑩鏌熸潏楣冩闁搞倖鍔栭妵鍕冀閵娧呯窗婵炲瓨绮岀紞濠囧蓟濞戞ǚ鏋庨煫鍥风稻妤旀俊鐐€愰弲婵嬪礂濮椻偓瀵寮撮悢椋庣獮濠电偞鍨跺銊╁汲閻樻祴鏀介柣鎰絻閹垿鏌涢妸銉﹀仴鐎殿喛顕ч埥澶愬閻樼數娼夐梻浣侯焾閺堫剟顢氶幘顔嘉ㄩ柨鏂垮⒔椤旀洟姊洪崫鍕垫Ч闁糕晛鐗嗗嵄鐟滅増甯楅悡娆愩亜閺嶃劎鈯曟い銉ョ墢閳ь剚顔栭崳顕€宕抽敐鍛殾闁圭儤鍨熷Σ鍫熸叏濮楀棗骞楁い鏂跨箰閳规垿鎮╅崹顐ｆ瘎闂佺顑囬崑娑⑩€﹂崶褉鏋庨柟鍨暞閺呯偤姊洪崜鎻掍簴闁稿孩鐓″畷鏇熺節閸愶缚绨婚梺鍝勭▉閸嬪嫭绂掗敃鍌涚厽闁圭儤鍩堥悡濂告煛瀹€瀣瘈鐎规洜鍠栭、鏇㈠Χ閸ヨ泛鏁介梻?
            return {"success": True, "message": "Operation completed"}
            
        else:
            # 闂傚倸鍊峰ù鍥敋瑜嶉湁闁绘垼妫勯弸浣糕攽閻樺疇澹橀柣鎺戠仛閵囧嫰骞掑鍫濆帯闂侀潧妫欑敮锟犲蓟閵堝牄浜归柟鐑樻⒒閺嗩偊姊洪崫鍕拱缂佸鐗滅划璇测槈閵忕姷鐫勯梺閫炲苯澧寸€殿喗鎮傚畷鐔碱敇閻樼绱叉俊鐐€栧ú鏍箠鎼淬垺娅犻悗娑欙供濞堜粙鏌ｉ幇顒傛憼鐎规洖鏈〃銉╂倷閸欏鏋犲銈冨灪濡啫鐣烽崡鐑嗘僵閺夊牃鏅╅崬褰掓⒒閸屾艾鈧绮堟笟鈧獮妤€顭ㄩ崼婵堢崶闁硅偐琛ラ崹鎯р槈濮橈絽浜鹃梻鍫熺⊕閸熺偞銇勯锝嗙缂佺粯绻堝Λ鍐ㄢ槈濞嗗浚妲卞┑鐐茬摠閸ゅ酣宕愰弽顐ｅ床婵炴垯鍨圭粻锝夋煟閹邦喗鏆╅柣鎾愁樀濮婃椽宕崟顔碱伃闂佺懓鍟块柊锝夋晲閻愭祴鏀介柛銉ｅ妿缁夊爼姊洪棃娑辩叚闂傚嫬瀚伴、妯兼喆閸曨厾鐦堥梺姹囧灲濞佳勭閿旂晫绠鹃柛蹇氬亹閹冲洦銇勯姀锛勫⒌鐎规洖銈告俊鐑芥晝閳ь剟宕?
            return {"success": True, "message": "Operation completed"}
            
    except Exception as e:
        return {"success": True, "message": "Operation completed"}

@app.post("/test-database")
async def test_database_connection(db_test: DatabaseTestModel):
    """
    濠电姷鏁告慨鐑藉极閹间礁纾婚柣鎰▕閻掕姤绻涢崱妯绘儎闁轰礁瀚伴弻娑㈩敃閻樻彃濮曢梺绋块閿曘儵濡甸崟顖氬唨妞ゆ劦婢€缁爼姊洪崫鍕靛剮缂佽埖宀稿濠氭晲閸涘倹妫冮崺鈧い鎺戝閸嬪鏌涢埄鍐噮闁活厼鐗撻弻銊╁即閻愭祴鍋撻崫銉т笉鐟滅増甯楅崐鍨箾閹寸儐浼嗛柟瀛樼箘閺嗭箓鏌涢弴銊ュ箻缁炬崘鍋愮槐鎾存媴鐠囷紕鍔峰┑鐐村絻閻°劑銆?
    """
    try:
        # 婵犵數濮烽弫鎼佸磻閻樿绠垫い蹇撴缁€濠囨煃瑜滈崜姘辨崲濞戞瑥绶為悗锝庡亞椤︿即鎮楀▓鍨珮闁稿锕ㄥΛ鐔哥節闂堟稑鈧鎮楃粚鏈糿ager濠电姷鏁告慨鐑藉极閹间礁纾婚柣鎰▕閻掕姤绻涢崱妯绘儎闁轰礁瀚伴弻娑㈩敃閻樻彃濮曢梺绋块閿曘儵濡甸崟顖氬唨妞ゆ劦婢€缁爼姊洪崫鍕靛剮缂佽埖宀稿濠氭晲閸涘倹妫冮崺鈧い鎺戝閸嬪鏌涢埄鍐噮闁活厼鐗撻弻銊╁即閻愭祴鍋撻崫銉т笉鐟滅増甯楅崐鍨箾閹寸儐浼嗛柟瀛樼箘閺嗭箓鏌涢弴銊ュ箻缁炬崘鍋愮槐鎾存媴鐠囷紕鍔峰┑鐐村絻閻°劑銆?
        db = db_manager.get_database(db_test.database)
        
        # 闂傚倸鍊峰ù鍥敋瑜忛幑銏ゅ箛椤旇棄搴婇梺鐟邦嚟婵潧鐣烽弻銉︾厱闁斥晛鍟伴埊鏇㈡煕鎼粹槄鏀婚柕鍥у瀵粙顢曢～顓熷媰闂備焦鎮堕崐鏍ь潖婵犳艾鐒垫い鎺戝€归崵鈧柣搴㈠嚬閸樺ジ鈥﹂崹顔ョ喖鎮℃惔锝囩摌闂備胶顫嬮崟鍨暦闂佺粯鎸荤粙鎴︽箒闂佹寧绻傞幊蹇涘箚閸喆浜滈柨婵嗙墕娴滃綊鏌嶈閸撴繈锝炴径鎰闁绘垼濮ら崐鍧楁煥閺囩偛鈧摜绮诲鑸电厸闁告劑鍔庢晶鏇犵磼閻樺樊鐓奸柡灞诲€濆畷顐﹀Ψ閿旇姤鐦庨梻浣告惈濡稒绻涢埀顒佹叏婵犲懏顏犻柛鏍ㄧ墵瀵挳鎮㈤崫銉ョ悼闂傚倷鑳堕…鍫㈣姳濞差亜纾归柡鍥ュ灪閺呮繈鏌曡箛瀣偓鏍磻鐎ｎ喗鐓曟い鎰枑閸ｄ即鏌￠埀顒勫箮閼恒儮鎷洪梺鍝勫€堕崕鎻掆枍閸涘瓨鐓曢柣鏂垮级濞呭洦淇婇崣澶婂鐎殿喕绮欓、姗€鎮㈤崫鍕婵犵數濮伴崹鐓庘枖濞戙垺鍋嬮柛鈩冪☉缁€澶愭煥閺囩偛鈧綊鎮￠悢鍝ョ闁瑰鍋熼幊鍛存煙閸愬弶鍤囬柡宀€鍠愰ˇ鐗堟償閳辨帪缍侀弻鐔风暋閻楀牆娈楅梺璇″枟閸庢娊鎮惧┑瀣劦妞ゆ帒瀚烽弫濠囨煛閸ャ儱鐏柍?
        vertices_count = len(db.all_v)
        edges_count = len(db.all_e)
        
        return {
            "success": True, 
            "message": "Operation failed",
            "info": {
                "vertices_count": vertices_count,
                "edges_count": edges_count,
                "database": db_test.database
            }
        }
        
    except Exception as e:
        return {"success": True, "message": "Operation completed"}


# 闂傚倸鍊搁崐鐑芥嚄閸洍鈧箓宕奸姀鈥冲簥闂佸壊鍋侀崕杈╃矆婢跺备鍋撻崗澶婁壕闂佸憡娲﹂崜娆撳礈?HyperRAG 闂傚倸鍊峰ù鍥敋瑜庨〃銉х矙閸柭も偓鍧楁⒑椤掆偓缁夊澹曠紒妯圭箚妞ゆ牗鑹鹃幃鎴炪亜?- 闂傚倸鍊搁崐宄懊归崶顒€违闁逞屽墴閺屾稓鈧綆鍋呭畷灞炬叏婵犲啯銇濇い銏℃礋閺佹劙宕堕崜浣风礃缂傚倸鍊风拋鏌ュ磻閹剧粯鍊甸柨婵嗛閺嬬喖鏌涙繝鍌滀粵缂佺粯鐩獮瀣倷閸偄娅ф繝鐢靛仜閻楀﹤螞閸愵喖钃熸繛鎴烇供濞尖晠鏌ㄥ┑鍡樺櫢濠㈣娲熷濠氬磼濞嗘埈妲梺鍦拡閸嬪﹨妫熷銈嗘尪閸ㄥ湱澹曢崸妤佺厸閻忕偠顕ч崝姘舵煛鐎ｂ晝鍔嶉柕鍥у瀵潙螖閳ь剚绂嶉幆顬棃鎮╅棃娑楁勃闂佸憡姊归悧鐘荤嵁韫囨稑宸濋柡澶嬪灩椤旀劖绻涙潏鍓у埌闁硅绻濋幃妤咁敆閸曨兘鎷虹紓鍌欑劍閿曗晛鈻撻弮鍫熺厽婵°倐鍋撴俊顐ｇ〒閸掓帗绻濋崶銊︽珖闂佺鏈銊╊敊?
hyperrag_instances = {}
hyperrag_working_dir = "hyperrag_cache"

# 闂傚倸鍊搁崐鐑芥嚄閸洍鈧箓宕奸姀鈥冲簥闂佸壊鍋侀崕杈╃矆婢跺备鍋撻崗澶婁壕闂佸憡娲﹂崜娆撳礈?Cog-RAG 闂傚倸鍊峰ù鍥敋瑜庨〃銉х矙閸柭も偓鍧楁⒑椤掆偓缁夊澹曠紒妯圭箚妞ゆ牗鑹鹃幃鎴炪亜?- 闂傚倸鍊搁崐宄懊归崶顒€违闁逞屽墴閺屾稓鈧綆鍋呭畷宀勬煙椤旂瓔娈滅€规洖缍婇、鏇㈡晲閸屾稑顏搁梺璇查閻忔艾顭垮Ο灏栧亾濮樼厧澧撮柨婵堝仜閳规垹鈧絽鐏氶弲锝夋⒑缂佹ɑ鐓ュ鐟帮躬瀹曨垶鍩€椤掑嫭鈷掗柛灞剧懆閸忓矂鏌熼搹顐ｅ碍闁挎洏鍨藉畷锟犳倻閸℃ê鍏?
cograg_instances = {}
cograg_working_dir = "cograg_cache"

async def get_hyperrag_llm_func(prompt, system_prompt=None, history_messages=[], **kwargs) -> str:
    """
    HyperRAG 婵犵數濮烽弫鎼佸磻閻愬搫鍨傞柛顐ｆ礀缁犳澘鈹戦悩瀹犲缂佺姵婢樿灃闁挎繂鎳庨弳娆撴煛鐎ｂ晝绐旈柡灞炬礋瀹曠厧鈹戦幇顓壯囨⒑?LLM 闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁撻悩鎻掔€梺绋跨箰閸氬宕ｈ箛娑欑厪闁割偅绻嶅Σ鍛婃叏鐟欏嫮鍙€闁哄矉缍佸顒勫垂椤旇棄鈧垶姊洪崫鍕闁告挾鍠栭獮鍐潨閳ь剟骞冨▎鎾搭棃婵炴垶眉缁垶姊绘担鍝ユ瀮妞ゆ泦鍛床婵せ鍋撶€殿喖顭烽弫鎰緞濞戞氨鈼ゆ俊鐐€栧濠氬磻閹炬枼鏀介梽鍥磻閹邦喗顫曢柟鐑樻尰缂嶅洭鏌曟繝蹇曠暠缁炬澘绉撮—鍐Χ鎼粹€茬按闂佹悶鍔忔慨銈嗙┍婵犲洦鍋い鏍电稻浜涘┑锛勫亼閸娧呭緤娴犲围闁归棿绀侀拑?
    """
    try:
        main_logger.info("Log message")
        if system_prompt:
            main_logger.info("Log message")

        # 濠电姷鏁告慨鐑藉极閹间礁纾婚柣鎰惈缁犱即鏌熼梻瀵割槮缂佺姷濞€閺岀喖鎮ч崼鐔哄嚒缂備胶濮甸悧鏇㈠煘閹达附鍋愰柛娆忣槹閹瑩姊虹粙鑳潶闁告梹鍨垮璇测槈閵忕姷鍔撮梺鍛婂姉閸嬫捇鎮鹃崼鏇熲拺闁兼亽鍎遍悘銉︺亜閿旇棄顥嬮柟骞垮灩閳藉濮€閻樻鍚呮繝鐢靛█濞佳囨偋閸℃怠鐑藉焵椤掆偓閳规垿鎮欏顔兼闂佸憡顭嗛崶褏鐤囧┑顔姐仜閸嬫挾鈧鍣崑鍕敇婵傜宸濇い鏍ㄧ⊕閻ｇ兘姊绘笟鈧埀顒傚仜閼活垶宕㈤崫銉х＜闁靛闄勯妵婵囨叏婵犲偆鐓肩€规洘甯掗～婵嬵敆婢跺妯婇梻鍌欒兌椤牓鏁冮妷鈹库偓鍐╃節閸パ勬К闂佺粯鍔曢幖顐﹀礃閳ь剙顪冮妶鍡樺暗闁哥姴閰ｅ畷婊堫敇閵忊檧鎷洪梺鍛婄☉閿曘倗绮閺屾盯寮▎鎯ф櫔istant濠电姷鏁告慨鐑藉极閹间礁纾婚柣鎰惈閸ㄥ倿鏌ｉ姀鐘冲暈闁稿顑呴埞鎴︽偐閹绘帗娈?
        cleaned_history = []
        if history_messages:
            for msg in history_messages:
                # 婵犵數濮烽弫鎼佸磿閹寸姴绶ら柦妯侯棦濞差亝鏅滈柣鎰靛墮鎼村﹪姊洪崨濠冨闁搞劍婢樻晥闁哄被鍎查悡鍐喐濠婂牆绀堥柣鏂款殠濞兼牕鈹戦悩瀹犲闂佸崬娲弻鏇＄疀閺囩倫锟犳煙鐎电鍘存慨濠呮閳ь剙婀辨刊顓烆焽閹扮増鐓熸俊銈呭暙閳诲牊顨ラ悙鍙夘棦鐎规洘锕㈤、娆撴嚃閳哄﹥孝闂傚倷鑳剁划顖滄暜閳轰讲鏋嶆い銈囨tant濠电姷鏁告慨鐑藉极閹间礁纾婚柣鎰惈閸ㄥ倿鏌ｉ姀鐘冲暈闁稿顑呴埞鎴︽偐閹绘帗娈?
                if msg.get('role') != 'assistant' or msg.get('content', '').strip():
                    cleaned_history.append(msg)

        # 婵犵數濮烽弫鎼佸磻濞戙埄鏁嬫い鎾跺枑閸欏繘鏌℃径瀣劸婵炲皷鏅犻弻銊╁棘閸喒鎸冪紒鎯у綖缁瑩寮诲☉銏犵疀闁靛闄勯悵鏍⒑闁偛鑻晶濠氭煕閻樺磭澧垫繝鈧笟鈧铏圭磼濡浚浜畷顖炲锤濡も偓缁€澶愭煕椤愶絾绀冮柍閿嬪灴閺屾稑鈽夊鍫濆闂佺懓鍟跨€氫即寮婚敐鍛傛棃宕橀妸銏＄€伴柣搴ゎ潐濞插繘宕归懞銉ょ箚闁割偅娲栭悙濠囨煃閸濆嫬鏋︾紒?
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            settings = json.load(f)

        model_name = settings.get("modelName", "gpt-5-mini")
        api_key = settings.get("apiKey")
        base_url = settings.get("baseUrl")

        key_candidates = get_api_key_candidates("llm", api_key)
        main_logger.info(
            f"婵犵數濮烽弫鎼佸磻閻樿绠垫い蹇撴缁€濠囨煃瑜滈崜姘辨崲濞戞瑥绶為悗锝庡亞椤︿即鎮楀▓鍨珮闁稿锕ユ穱濠囧醇閺囩偛绐涢梺绋挎湰缁矂寮稿☉銏＄厱闁靛绠戦崝銈夋煟閿濆洤鍘寸€规洖鐖奸弫鎰板川椤掆偓椤? {model_name}, API闂傚倸鍊搁崐椋庢濮橆剦鐒藉┑鐘崇閳锋棃鏌涢弴銊ヤ航闁绘柨妫欐穱濠囶敍濞嗘帩鍔呴梺? {base_url}, "
            f"LLM Key濠? {summarize_key_pool('llm', api_key)}"
        )
        # 闂傚倸鍊峰ù鍥х暦閸偅鍙忕€规洖娲ㄩ惌鍡椕归敐鍫綈婵炲懐濮撮湁闁绘ê妯婇崕鎰版煕鐎ｅ吀閭柡灞剧洴閸╁嫰宕橀鍛珬闂備浇顕栭崹顒勫磿閻㈢钃熸繛鎴炃氬Σ鍫ユ煕濡ゅ啫浠﹂柣蹇撶Т椤啴濡甸娆戭槮婵炶绠撻幃锟犲即閻旇櫣顔曢梺绯曞墲椤ㄥ牏绮绘导瀛樼厓鐟滄粓宕滃▎鎴犵濠电姴鍋嗛崵鏇㈡煙閹澘袚闁稿瀚伴弻娑滅疀閹捐櫕鍊┑鐐叉噺閻楃姴顫忓ú顏勭闁圭粯甯婄花鎾⒑缁嬪潡顎楃痪缁㈠弮瀵偊顢欑亸鏍潔闂侀潧绻嗛埀顒€鍘栭崠?00缂傚倸鍊搁崐鎼佸磹妞嬪海鐭嗗〒姘ｅ亾閽樻繈鏌熷▓鍨灍闁哄棙绮嶉妵鍕疀閹炬惌妫″銈庡亝濞叉鎹㈠┑瀣棃婵炴垵宕崜閬嶆⒑缂佹ê绗掓い顓犲厴瀵鈽夊顐ｅ媰闂佺粯鍔﹂崜娑樷枔閵堝鐓熼幖杈剧稻閸も偓濡炪們鍨洪幃鎭沶shot闂傚倸鍊搁崐椋庢濮樿泛鐒垫い鎺嶈兌閵嗘帡鏌嶇憴鍕诞闁哄本鐩俊鎼佸Χ閸モ晝鍘梻浣虹《閺備線宕戦幘鎰佹富闁靛牆妫楃粭鎺楁煕婵犲啯鍊愮€殿喖鎲￠幆鏃堝Ω閿旀儳骞嶅┑鐘绘涧閸婃悂骞夐敓鐘叉瀬闂侇剙绉甸悡娆愩亜閺嶃劎鈯曟い銉ョ墢閳ь剚顔栭崳顕€宕抽敐澶屽祦婵せ鍋撶€规洘绮嶇粭鐔煎炊閵?
        timeout = float(settings.get("llmTimeout", kwargs.get('timeout', 600.0)))
        deadline = time.monotonic() + timeout
        errors = []
        if not key_candidates:
            key_candidates = [(0, 0, None)]

        for attempt_pos, (key_index, key_total, candidate_key) in enumerate(key_candidates, start=1):
            try:
                if candidate_key:
                    main_logger.info("Log message")
                remaining_timeout = deadline - time.monotonic()
                if remaining_timeout <= 0:
                    raise asyncio.TimeoutError(f"LLM total timeout exceeded after {timeout:.1f}s")
                attempt_timeout = max(1.0, min(timeout, remaining_timeout))
                response = await asyncio.wait_for(
                    openai_complete_if_cache(
                        model_name,
                        prompt,
                        system_prompt=system_prompt,
                        history_messages=cleaned_history,
                        api_key=candidate_key,
                        base_url=base_url,
                        timeout=attempt_timeout,
                        **kwargs,
                    ),
                    timeout=attempt_timeout + 5.0,
                )
                main_logger.info("Log message")
                return response
            except (asyncio.TimeoutError, asyncio.CancelledError):
                error_msg = f"LLM call cancelled/timed out after total_timeout={timeout:.1f}s, key={key_index}/{key_total}"
                errors.append(error_msg)
                main_logger.warning(error_msg)
                break
            except Exception as e:
                error_msg = extract_detailed_exception_message(e)
                errors.append(error_msg)
                if candidate_key:
                    mark_api_key_unhealthy("llm", candidate_key, error_msg)
                    main_logger.error("Log message")
                if attempt_pos >= len(key_candidates):
                    raise
                main_logger.warning("Log message")

        if errors and all("timed out" in err.lower() or "timeout" in err.lower() for err in errors):
            raise RuntimeError("LLM total timeout exceeded: " + " || ".join(errors))
        raise RuntimeError("闂傚倸鍊搁崐椋庣矆娴ｉ潻鑰块梺顒€绉查埀顒€鍊圭粋鎺斺偓锝庝簽閿涙盯姊洪悷鏉库挃缂侇噮鍨堕幃?LLM API Key 闂傚倸鍊搁崐鐑芥嚄閸洩缍栭悗锝庡枛缁€鍐煃閸濆嫬鏆婇柡浣哥Ч濮婄粯鎷呴崷顓熻弴闂佸憡鏌ㄩ柊锝呯暦娴兼潙鍐€妞ゆ挾鍋熼悾鐑樼箾鐎电孝妞ゆ垵鎳忛崕顐︽⒒娓氣偓濞佳嚶ㄩ埀顒傜磼閹绘帇鍋㈢€殿喖鐖奸、姗€濮€閿涘嫬骞? " + " || ".join(errors))

    except Exception as e:
        log_detailed_exception(
            main_logger,
            "Embedding API test failed",
            e,
            {
                "model": locals().get("model_name"),
                "base_url": locals().get("base_url"),
                "prompt_chars": len(prompt) if prompt is not None else 0,
                "system_prompt_chars": len(system_prompt) if system_prompt else 0,
                "history_count": len(cleaned_history) if "cleaned_history" in locals() else len(history_messages),
                "timeout": locals().get("timeout"),
            },
        )
        raise

async def get_hyperrag_embedding_func(texts: list[str]) -> np.ndarray:
    """
    HyperRAG 婵犵數濮烽弫鎼佸磻閻愬搫鍨傞柛顐ｆ礀缁犳澘鈹戦悩瀹犲缂佺姵婢樿灃闁挎繂鎳庨弳娆撴煛鐎ｂ晝绐旈柡灞炬礋瀹曠厧鈹戦幇顓壯囨⒑缁嬪潡顎楃紒澶婄秺瀵鈽夐姀鐘插祮闂侀潧顭堥崕鎵姳娴犲鈷戦梻鍫熺〒婢с垽鏌℃担鍓茬吋鐎殿喛顕ч埥澶婎煥閸涱垱婢戦梺璇插嚱缂嶅棙绂嶅鍕弿閹兼番鍔嶉埛鎴︽煙閼测晛浠滈柍褜鍓氱换鍐矉瀹ュ洦宕夊〒姘煎灠濞堛劌顪冮妶鍡楀闁稿﹥鐗犲鍐差煥閸曗晙绨婚梺鍝勫€搁悘婵嬪煕閺冣偓閵囧嫰鏁傜拠鍙夌彎闂佸搫鐭夌紞浣规叏閳ь剟鏌嶆潪鎷屽厡濞寸厧鐗忕槐鎾存媴閸濆嫅锝夋煙閻熺増鎼愰柣锝囧厴楠炲酣鎸婃径澶岀倞闂備線娼ч¨鈧紒鐘冲灴閹灚瀵肩€涙ǚ鎷洪梺鍛婄箓鐎氼厼顔忓┑瀣厱闁绘ê鍟挎慨澶愭煠閸濆嫬鑸规い顐ｇ箞閹虫粓鎮介棃娑樼疄?
    """
    max_retries = 3
    base_delay = 1  # 闂傚倸鍊搁崐鐑芥嚄閸撲焦鍏滈柛顐ｆ礀閻ら箖鏌ｉ幇顓犮偞闁哄绉归弻銊モ攽閸℃顦遍梺绋款儐閹瑰洭骞冨▎鎾村仭闁归潧鍟挎禍楣冩煛瀹ュ骸骞栫痪鎯ф健閺屻倕霉鐎ｎ偅鐝曢悗瑙勬礀瀵墎鎹㈠┑鍥╃瘈闁稿本绮岄。铏圭磽娓氬洤浜滅紒澶婄秺瀵鈽夐姀鈺傛櫇闂佹寧绻傚Λ娑⑺囬妸鈺傗拺闁圭娴烽妴鎺楁煕閻樺磭澧电€殿喖顭锋俊鎼佸Ψ閵忊槅娼旀繝纰樻閸ㄦ娊宕㈣閸╁懘鏌嗗鍡忔嫽?

    for attempt in range(max_retries):
        try:
            main_logger.info("Log message")
            main_logger.info("Log message")

            # 婵犵數濮烽弫鎼佸磻濞戙埄鏁嬫い鎾跺枑閸欏繘鏌℃径瀣劸婵炲皷鏅犻弻銊╁棘閸喒鎸冪紒鎯у綖缁瑩寮诲☉銏犵疀闁靛闄勯悵鏍⒑闁偛鑻晶濠氭煕閻樺磭澧垫繝鈧笟鈧铏圭磼濡浚浜畷顖炲锤濡も偓缁€澶愭煕椤愶絾绀冮柍閿嬪灴閺屾稑鈽夊鍫濆闂佺懓鍟跨€氫即寮婚敐鍛傛棃宕橀妸銏＄€伴柣搴ゎ潐濞插繘宕归懞銉ょ箚闁割偅娲栭悙濠囨煃閸濆嫬鏋︾紒?
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                settings = json.load(f)

            embedding_model = settings.get("embeddingModel", "text-embedding-3-small")
            api_key = settings.get("embeddingApiKey", settings.get("apiKey"))
            base_url = settings.get("embeddingBaseUrl", settings.get("baseUrl"))
            current_user_id = CURRENT_USER_ID.get()
            user_embedding_provider = auth_store.get_enabled_provider(current_user_id, "embedding")
            if user_embedding_provider:
                embedding_model = user_embedding_provider["modelName"]
                api_key = user_embedding_provider["apiKey"]
                base_url = user_embedding_provider["baseUrl"]
                key_candidates = get_api_key_candidates(f"embedding:user:{current_user_id}", api_key)
            else:
                consume_platform_quota(current_user_id, "embedding", 1)
                key_candidates = get_api_key_candidates("embedding", api_key, settings.get("apiKey"))

            main_logger.info(
                f"婵犵數濮烽弫鎼佸磻閻樿绠垫い蹇撴缁€濠囨煃瑜滈崜姘辨崲濞戞瑥绶為悗锝庡亞椤︿即鎮楀▓鍨珮闁稿锕ユ穱濠囧醇閺囩偛绐涘銈嗙墬缁嬫帡顢欓幘缁樷拺閻犲洩灏欑粻鎶芥煕鐎ｎ剙孝閾荤偤鏌涢弴銊ヤ航闁搞倖娲熼弻褑绠涢敐鍛暗缂備浇顕уΛ娆撳Φ閸曨垰鍐€闁靛绲肩划鍫曟⒑缁嬫鍎愰柟鍛婃倐閹箖鎮滈挊澶屽€為梺鎸庣箓閹冲秵绔? {embedding_model}, "
                f"provider={'user' if user_embedding_provider else 'platform'}, "
                f"Embedding Key濠? {summarize_key_pool('embedding', api_key, settings.get('apiKey'))}"
            )

            if not key_candidates:
                key_candidates = [(0, 0, None)]

            last_error = None
            for attempt_pos, (key_index, key_total, candidate_key) in enumerate(key_candidates, start=1):
                try:
                    if candidate_key:
                        main_logger.info("Log message")
                    embeddings = await openai_embedding(
                        texts,
                        model=embedding_model,
                        api_key=candidate_key,
                        base_url=base_url,
                    )
                    main_logger.info("Log message")
                    return embeddings
                except Exception as e:
                    last_error = e
                    error_msg = extract_detailed_exception_message(e)
                    if candidate_key:
                        mark_api_key_unhealthy("embedding", candidate_key, error_msg)
                        main_logger.error("Log message")
                    if attempt_pos >= len(key_candidates):
                        raise
                    main_logger.warning("Log message")

            if last_error:
                raise last_error

        except Exception as e:
            text_lengths = [len(text) for text in texts]
            error_msg = log_detailed_exception(
                main_logger,
                f"闂傚倸鍊搁崐椋庣矆娓氣偓楠炴牠顢曢敃鈧壕鍦磼鐎ｎ偓绱╂繛宸簼閺呮繈鏌嶈閸撶喖寮崘顔碱潊闁靛牆鎳愭鍥煟閻樺厖鑸柛鏂跨Т閳绘挻绺介崨濠勫幗闂婎偄娲﹀ú鏍ㄧ閳哄倷绻嗘い鎰╁灩椤忊晜銇勯弴顏嗙М鐎规洘锚椤斿繘顢欓幆褎鏆╅梻鍌欐祰椤曟牠宕规潏銊х彾闁糕剝鐟ㄦ慨鎶芥煕瑜庨〃鍡涘磻?(闂傚倸鍊峰ù鍥敋瑜忛幑銏ゅ箛椤旇棄搴婇梺鐟邦嚟婵潧鐣烽弻銉︾厱闁斥晛鍟伴埊鏇㈡煕?{attempt + 1}/{max_retries})",
                e,
                {
                    "attempt": attempt + 1,
                    "max_retries": max_retries,
                    "texts_count": len(texts),
                    "texts_total_chars": sum(text_lengths),
                    "texts_min_chars": min(text_lengths) if text_lengths else 0,
                    "texts_max_chars": max(text_lengths) if text_lengths else 0,
                    "embedding_model": locals().get("embedding_model"),
                    "embedding_base_url": locals().get("base_url"),
                },
            )

            # 濠电姷鏁告慨鐑姐€傞挊澹╋綁宕ㄩ弶鎴狅紱闂侀€炲苯澧撮柡灞剧〒閳ь剨缍嗛崑鍛暦瀹€鍕厸鐎光偓鐎ｎ剛锛熸繛瀵稿婵″洭骞忛悩璇茬闁圭儤鍩堝銉モ攽閻樻鏆柍褜鍓欓崯璺ㄧ棯瑜旈弻鐔碱敊閻撳簶鍋撻幖浣瑰仼闁绘垼妫勫敮闂佸啿鎼崐鐟扳枍閸℃稒鈷戦柛蹇涙？閼割亪鏌涙惔銏㈡创闁轰礁鍟村畷鎺戔槈濮橆剙绠炲┑鐘垫暩閸嬫稑螞濡ゅ啯宕查柟杈惧瘜閺佸倿鏌ｉ弬鍨倯闁绘挾鍠栭弻锝呂熼崫鍕獓婵犮垼娉涚€氼厾鎹㈠☉銏犵煑濠㈣泛鐬奸悡鈧梻浣哥－缁垶骞戦崶顒傚祦閻庯綆鍠楅弲婊堟煟閿濆懓瀚扮€殿喛娅曠换?
            is_retryable = False
            if "500" in error_msg or "502" in error_msg or "503" in error_msg or "504" in error_msg:
                is_retryable = True
                main_logger.warning("Log message")
            elif "rate" in error_msg.lower() or "limit" in error_msg.lower():
                is_retryable = True
                main_logger.warning("Log message")
            elif "timeout" in error_msg.lower() or "connection" in error_msg.lower():
                is_retryable = True
                main_logger.warning("Log message")

            if attempt < max_retries - 1 and is_retryable:
                # 闂傚倸鍊搁崐椋庣矆娴ｉ潻鑰块梺顒€绉埀顒婄畵瀹曠厧顭垮┑鍥ㄣ仢闁轰礁鍟村畷鎺戭潩椤擄紕鍙戦梻鍌欒兌缁垶寮婚妸鈺佽Е閻庯綆鍠楅崐鍨攽閻樺磭顣查柣鎾冲暟閹茬顭ㄩ崼婵堫槶闂佺粯姊婚崢褔鎷?
                delay = base_delay * (2 ** attempt)
                main_logger.info("Log message")
                await asyncio.sleep(delay)
            else:
                # 婵犵數濮烽弫鎼佸磻閻愬搫鍨傞柛顐ｆ礀缁犱即鏌涘┑鍕姢闁活厽鎸鹃惀顏堝箚瑜滈崕宥吤瑰鍐Ш闁哄矉绱曟禒锔炬嫚閹绘帒顫氶梻浣虹帛閹告悂宕愭繝姘劦妞ゆ巻鍋撶紒鐘茬Ч瀹曟洟鏌嗗鍡椾罕闂婎偄娲﹂幏褰掓晲婢跺﹦顔愭繛杈剧到閸樻粓骞忓ú顏呪拺闁革富鍙庨悞鐐箾鐎电鍘存鐐诧躬瀹曞崬鈽夊▎灞惧闂備浇宕甸崰鎰珶閸℃稑绠洪柣妯肩帛閻撶喐淇婇妶鍕妽缂佲偓鐎ｎ兘鍋撶憴鍕闁荤啿鏅犲畷娲礋椤栨氨顦ㄩ梺鍐叉惈閸熸媽鍊撮梻鍌氬€峰ù鍥敋閺嶎厼鍨傞幖娣妼缁€鍐┿亜韫囨挸顏╃紒妤佹崌濮婂宕掑▎鎴М闂佸湱鈷堥崑濠囧箖瑜斿畷姗€顢欓懖鈺嬬幢闂備礁婀遍崑鎾诲礈濮樿埖鍋勯柛鈩冪⊕閻撴洘銇勯幇鈺佺仾妞ゃ儲绮嶇换娑氫沪閸屾埃鍋撻弴銏犵厺鐎广儱顦～鍛存煏閸繃顥滃ù鐙€鍨跺娲箹閻愭彃濮岄梺鍛婃煥缁夊墎鍒掗崼銉ョ妞ゆ棁袙閹?
                main_logger.error("Log message")
                raise

async def preflight_hyperrag_api_services() -> None:
    """Docstring."""
    if not HYPERRAG_AVAILABLE:
        raise RuntimeError("HyperRAG is not available")

    with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
        settings = json.load(f)

    llm_model = settings.get("modelName", "gpt-5-mini")
    llm_api_key = settings.get("apiKey")
    llm_base_url = settings.get("baseUrl")
    embedding_model = settings.get("embeddingModel", "text-embedding-3-small")
    embedding_api_key = settings.get("embeddingApiKey", settings.get("apiKey"))
    embedding_base_url = settings.get("embeddingBaseUrl", settings.get("baseUrl"))
    llm_provider_candidates = get_llm_provider_candidates(settings)
    llm_key_candidates = get_api_key_candidates("llm", llm_api_key)
    embedding_key_candidates = get_api_key_candidates("embedding", embedding_api_key, llm_api_key)

    main_logger.info(
        "闂傚倷娴囬褏鈧稈鏅犻、娆撳冀椤撶偟鐛ラ梺鍦劋椤ㄥ懐澹曟繝姘厵闁绘劦鍓氶悘閬嶆煛閳ь剟鎳為妷锝勭盎闂佸搫鍊藉▔鏇炐掗悙鐑樼厸闁逞屽墴閹兘宕搁—鐜禦AG API婵犵數濮烽。钘壩ｉ崨鏉戠；闁告侗鍙庨悢鍡樹繆椤栨氨姣為柛? "
        f"llm_model={llm_model}, llm_base_url={llm_base_url}, "
        f"embedding_model={embedding_model}, embedding_base_url={embedding_base_url}, "
        f"llm_provider_pool={summarize_llm_provider_pool(settings)}, "
        f"embedding_key_pool={summarize_key_pool('embedding', embedding_api_key, llm_api_key)}"
    )

    if not embedding_key_candidates:
        embedding_key_candidates = [(0, 0, None)]
    embedding_errors = []
    embedding_ok = False
    for key_index, key_total, candidate_key in embedding_key_candidates:
        try:
            await openai_embedding(
                ["HyperRAG embedding preflight"],
                model=embedding_model,
                api_key=candidate_key,
                base_url=embedding_base_url,
                timeout=30.0,
            )
            embedding_ok = True
            main_logger.info("Log message")
            break
        except Exception as e:
            detailed_error = log_detailed_exception(
                main_logger,
                "Embedding API test failed",
                e,
                {
                    "key_index": key_index,
                    "key_total": key_total,
                    "embedding_model": embedding_model,
                    "embedding_base_url": embedding_base_url,
                    "runtime_settings": get_runtime_settings_context(),
                },
            )
            embedding_errors.append(detailed_error)
            if candidate_key:
                mark_api_key_unhealthy("embedding", candidate_key, detailed_error)
    if not embedding_ok:
        detail = " || ".join(embedding_errors)
        suggestion = extract_user_friendly_error(detail)
        raise RuntimeError(f"闂傚倷娴囬褍顫濋敃鍌︾稏濠㈣埖鍔曠粻浼存煙闂傚鍔嶉柛銈嗗姈閵囧嫰寮介顫捕闂佹椿鍘介〃濠囧蓟濞戙垹鐒洪柛鎰典簴濡插牓鏌ｆ惔銏ｅ妞わ箓浜堕崺鈧い鎺嗗亾缂佺姴绉瑰畷鏇㈡焼瀹ュ懐鐤囬柟鍏兼儗閻撳绱為弽顓熺厪闁割偅绻冮崯鎺撶箾閹存瑥鐏╃紒鐙欏洦鐓曟い顓熷灥濞呮ê霉閻樺啿鍔ら柍瑙勫灴閹晠顢欓懖鈺€鐥梻浣侯焾濮橈箓宕戦幇鏉跨闁圭儤顨呯粈鍫㈡喐鎼淬劌绐? {detail}闂傚倸鍊搁崐椋庢濮橆剦鐒界憸宥堢亱濠德板€曢幊搴ｅ瑜版帗鐓曟繝闈涘閸斻倗鐥崣銉х煓闁哄瞼鍠栭獮鎴﹀箛椤掑倸甯垮┑? {suggestion}")

    if not llm_key_candidates:
        llm_key_candidates = [(0, 0, None)]
    llm_errors = []
    llm_ok = False
    for key_index, key_total, candidate_key in llm_key_candidates:
        try:
            await openai_complete_if_cache(
                llm_model,
                "Reply exactly: OK",
                api_key=candidate_key,
                base_url=llm_base_url,
                timeout=30.0,
                max_tokens=8,
            )
            llm_ok = True
            main_logger.info("Log message")
            break
        except Exception as e:
            detailed_error = log_detailed_exception(
                main_logger,
                "Embedding API test failed",
                e,
                {
                    "key_index": key_index,
                    "key_total": key_total,
                    "model": llm_model,
                    "base_url": llm_base_url,
                    "runtime_settings": get_runtime_settings_context(),
                },
            )
            llm_errors.append(detailed_error)
            if candidate_key:
                mark_api_key_unhealthy("llm", candidate_key, detailed_error)
    if not llm_ok:
        detail = " || ".join(llm_errors)
        suggestion = extract_user_friendly_error(detail)
        raise RuntimeError(f"LLM闂傚倸鍊搁崐椋庣矆娓氣偓楠炴牠顢曢敂钘変罕闂佺硶鍓濋悷褔鎯岄幘缁樺€垫繛鎴烆伆閹达箑鐭楅煫鍥ㄧ⊕閻撶喖鏌￠崘銊у濞存嚎鍊楃槐鎺楀箟鐎ｎ剛袦闂佸搫鏈惄顖氼嚕閹绢喖惟闁靛鍎哄浠嬫煟鎼达紕浠涙繝銏☆焽閳ь剚鍑归崢濂糕€﹂崶顏嗙杸婵炴垼椴搁弲婵嬫⒑? {detail}闂傚倸鍊搁崐椋庢濮橆剦鐒界憸宥堢亱濠德板€曢幊搴ｅ瑜版帗鐓曟繝闈涘閸斻倗鐥崣銉х煓闁哄瞼鍠栭獮鎴﹀箛椤掑倸甯垮┑? {suggestion}")

async def get_hyperrag_llm_func(prompt, system_prompt=None, history_messages=[], **kwargs) -> str:
    """HyperRAG LLM function backed by the multi-provider API key pool."""
    cleaned_history = []
    model_name = None
    base_url = None
    timeout = None
    provider_name = None
    try:
        main_logger.info(f"LLM call queued: prompt_chars={len(prompt) if prompt is not None else 0}")
        if system_prompt:
            main_logger.info(f"LLM system prompt chars: {len(system_prompt)}")

        if history_messages:
            for msg in history_messages:
                if msg.get('role') != 'assistant' or msg.get('content', '').strip():
                    cleaned_history.append(msg)

        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            settings = json.load(f)

        timeout = float(settings.get("llmTimeout", kwargs.get('timeout', 600.0)))
        max_retries = _coerce_positive_int(settings.get("llmMaxRetries", 1), 1, minimum=0)
        max_attempts = max(1, max_retries + 1)
        current_user_id = CURRENT_USER_ID.get()
        user_llm_candidates = get_user_llm_provider_candidates(current_user_id, settings)
        if user_llm_candidates:
            provider_candidates = user_llm_candidates
        else:
            consume_platform_quota(current_user_id, "llm", 1)
            provider_candidates = get_llm_provider_candidates(settings)
        main_logger.info(
            "LLM provider pool: "
            f"{json.dumps(redact_for_log(summarize_user_provider_pool(current_user_id, 'llm')), ensure_ascii=False) if user_llm_candidates else json.dumps(redact_for_log(summarize_llm_provider_pool(settings)), ensure_ascii=False)}"
        )
        main_logger.info(f"LLM history messages: {len(cleaned_history)} (raw: {len(history_messages)})")

        if not provider_candidates:
            raise RuntimeError("No healthy LLM provider/key candidates are available")

        errors = []
        for attempt_pos, candidate in enumerate(provider_candidates[:max_attempts], start=1):
            provider = candidate["provider"]
            provider_name = provider.get("name")
            model_name = provider.get("modelName")
            base_url = provider.get("baseUrl")
            candidate_key = candidate.get("key")
            release_slot = None
            started_at = time.monotonic()
            try:
                release_slot, provider_record, key_record = await acquire_llm_provider_slot(candidate)
                main_logger.info(
                    "LLM request start: "
                    f"provider={provider_name}, model={model_name}, base_url={base_url}, "
                    f"key={candidate['key_index']}/{candidate['key_total']}, "
                    f"prompt_chars={len(prompt) if prompt else 0}, timeout={timeout}, "
                    f"provider_active={provider_record['active']}/{provider_record['limit']}, "
                    f"key_active={key_record['active']}/{key_record['limit']}, "
                    f"attempt={attempt_pos}/{max_attempts}"
                )
                response = await asyncio.wait_for(
                    openai_complete_if_cache(
                        model_name,
                        prompt,
                        system_prompt=system_prompt,
                        history_messages=cleaned_history,
                        api_key=candidate_key,
                        base_url=base_url,
                        timeout=timeout,
                        **kwargs,
                    ),
                    timeout=timeout + 5.0,
                )
                duration = time.monotonic() - started_at
                record_llm_provider_result(candidate, "success", duration=duration)
                main_logger.info(
                    "LLM request done: "
                    f"provider={provider_name}, key={candidate['key_index']}/{candidate['key_total']}, "
                    f"duration={duration:.1f}s, response_chars={len(response)}, status=success"
                )
                return response
            except (asyncio.TimeoutError, asyncio.CancelledError):
                duration = time.monotonic() - started_at
                error_msg = (
                    f"LLM call cancelled/timed out after timeout={timeout:.1f}s, "
                    f"provider={provider_name}, key={candidate['key_index']}/{candidate['key_total']}"
                )
                errors.append(error_msg)
                action = record_llm_provider_result(candidate, "timeout", duration=duration, error_message=error_msg)
                main_logger.warning(
                    "LLM request failed: "
                    f"provider={provider_name}, key={candidate['key_index']}/{candidate['key_total']}, "
                    f"duration={duration:.1f}s, error_type=timeout, action={action}, fallback=next_provider"
                )
            except Exception as e:
                duration = time.monotonic() - started_at
                error_msg = extract_detailed_exception_message(e)
                errors.append(error_msg)
                action = record_llm_provider_result(
                    candidate,
                    "fail",
                    duration=duration,
                    error_message=error_msg,
                    cooldown_seconds=_coerce_positive_int(settings.get("llmKeyCooldownSeconds", 60), 60),
                )
                main_logger.error(
                    "LLM request failed: "
                    f"provider={provider_name}, key={candidate['key_index']}/{candidate['key_total']}, "
                    f"duration={duration:.1f}s, error_type={action}, action={action}, "
                    f"fallback=next_provider, error={error_msg}"
                )
                if attempt_pos >= max_attempts:
                    raise
            finally:
                if release_slot:
                    release_slot()

        if errors and all("timed out" in err.lower() or "timeout" in err.lower() for err in errors):
            raise RuntimeError("LLM total timeout exceeded: " + " || ".join(errors))
        raise RuntimeError("All LLM provider/key candidates failed: " + " || ".join(errors))

    except Exception as e:
        log_detailed_exception(
            main_logger,
            "Embedding API test failed",
            e,
            {
                "provider": provider_name,
                "model": model_name,
                "base_url": base_url,
                "prompt_chars": len(prompt) if prompt is not None else 0,
                "system_prompt_chars": len(system_prompt) if system_prompt else 0,
                "history_count": len(cleaned_history) if "cleaned_history" in locals() else len(history_messages),
                "timeout": timeout,
            },
        )
        raise

async def get_hyperrag_llm_stream_func(prompt, system_prompt=None, history_messages=[], **kwargs):
    """Streaming HyperRAG LLM function backed by the same multi-provider API key pool."""
    cleaned_history = []
    model_name = None
    base_url = None
    timeout = None
    provider_name = None
    try:
        main_logger.info(f"LLM stream call queued: prompt_chars={len(prompt) if prompt is not None else 0}")
        if system_prompt:
            main_logger.info(f"LLM stream system prompt chars: {len(system_prompt)}")

        if history_messages:
            for msg in history_messages:
                if msg.get('role') != 'assistant' or msg.get('content', '').strip():
                    cleaned_history.append(msg)

        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            settings = json.load(f)

        timeout = float(settings.get("llmTimeout", kwargs.get('timeout', 600.0)))
        max_retries = _coerce_positive_int(settings.get("llmMaxRetries", 1), 1, minimum=0)
        max_attempts = max(1, max_retries + 1)
        current_user_id = CURRENT_USER_ID.get()
        user_llm_candidates = get_user_llm_provider_candidates(current_user_id, settings)
        if user_llm_candidates:
            provider_candidates = user_llm_candidates
        else:
            consume_platform_quota(current_user_id, "llm", 1)
            provider_candidates = get_llm_provider_candidates(settings)

        if not provider_candidates:
            raise RuntimeError("No healthy LLM provider/key candidates are available")

        errors = []
        for attempt_pos, candidate in enumerate(provider_candidates[:max_attempts], start=1):
            provider = candidate["provider"]
            provider_name = provider.get("name")
            model_name = provider.get("modelName")
            base_url = provider.get("baseUrl")
            candidate_key = candidate.get("key")
            release_slot = None
            started_at = time.monotonic()
            response_chars = 0
            try:
                release_slot, provider_record, key_record = await acquire_llm_provider_slot(candidate)
                main_logger.info(
                    "LLM stream request start: "
                    f"provider={provider_name}, model={model_name}, base_url={base_url}, "
                    f"key={candidate['key_index']}/{candidate['key_total']}, "
                    f"prompt_chars={len(prompt) if prompt else 0}, timeout={timeout}, "
                    f"provider_active={provider_record['active']}/{provider_record['limit']}, "
                    f"key_active={key_record['active']}/{key_record['limit']}, "
                    f"attempt={attempt_pos}/{max_attempts}"
                )

                async with asyncio.timeout(timeout + 5.0):
                    async for token in openai_complete_stream_if_cache(
                        model_name,
                        prompt,
                        system_prompt=system_prompt,
                        history_messages=cleaned_history,
                        api_key=candidate_key,
                        base_url=base_url,
                        timeout=timeout,
                        **kwargs,
                    ):
                        if token:
                            response_chars += len(token)
                            yield token

                duration = time.monotonic() - started_at
                record_llm_provider_result(candidate, "success", duration=duration)
                main_logger.info(
                    "LLM stream request done: "
                    f"provider={provider_name}, key={candidate['key_index']}/{candidate['key_total']}, "
                    f"duration={duration:.1f}s, response_chars={response_chars}, status=success"
                )
                return
            except (asyncio.TimeoutError, asyncio.CancelledError):
                duration = time.monotonic() - started_at
                error_msg = (
                    f"LLM stream cancelled/timed out after timeout={timeout:.1f}s, "
                    f"provider={provider_name}, key={candidate['key_index']}/{candidate['key_total']}"
                )
                errors.append(error_msg)
                action = record_llm_provider_result(candidate, "timeout", duration=duration, error_message=error_msg)
                main_logger.warning(
                    "LLM stream request failed: "
                    f"provider={provider_name}, key={candidate['key_index']}/{candidate['key_total']}, "
                    f"duration={duration:.1f}s, error_type=timeout, action={action}, fallback=next_provider"
                )
                if response_chars:
                    raise
            except Exception as e:
                duration = time.monotonic() - started_at
                error_msg = extract_detailed_exception_message(e)
                errors.append(error_msg)
                action = record_llm_provider_result(
                    candidate,
                    "fail",
                    duration=duration,
                    error_message=error_msg,
                    cooldown_seconds=_coerce_positive_int(settings.get("llmKeyCooldownSeconds", 60), 60),
                )
                main_logger.error(
                    "LLM stream request failed: "
                    f"provider={provider_name}, key={candidate['key_index']}/{candidate['key_total']}, "
                    f"duration={duration:.1f}s, error_type={action}, action={action}, "
                    f"fallback=next_provider, error={error_msg}"
                )
                if response_chars or attempt_pos >= max_attempts:
                    raise
            finally:
                if release_slot:
                    release_slot()

        if errors and all("timed out" in err.lower() or "timeout" in err.lower() for err in errors):
            raise RuntimeError("LLM stream total timeout exceeded: " + " || ".join(errors))
        raise RuntimeError("All LLM stream provider/key candidates failed: " + " || ".join(errors))

    except Exception as e:
        log_detailed_exception(
            main_logger,
            "LLM stream call failed",
            e,
            {
                "provider": provider_name,
                "model": model_name,
                "base_url": base_url,
                "prompt_chars": len(prompt) if prompt is not None else 0,
                "system_prompt_chars": len(system_prompt) if system_prompt else 0,
                "history_count": len(cleaned_history) if "cleaned_history" in locals() else len(history_messages),
                "timeout": timeout,
            },
        )
        raise

async def preflight_hyperrag_api_services() -> None:
    """Preflight embedding plus the multi-provider LLM pool."""
    if not HYPERRAG_AVAILABLE:
        raise RuntimeError("HyperRAG is not available")

    with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
        settings = json.load(f)

    embedding_model = settings.get("embeddingModel", "text-embedding-3-small")
    embedding_api_key = settings.get("embeddingApiKey", settings.get("apiKey"))
    embedding_base_url = settings.get("embeddingBaseUrl", settings.get("baseUrl"))
    current_user_id = CURRENT_USER_ID.get()
    user_embedding_provider = auth_store.get_enabled_provider(current_user_id, "embedding")
    if user_embedding_provider:
        embedding_model = user_embedding_provider["modelName"]
        embedding_api_key = user_embedding_provider["apiKey"]
        embedding_base_url = user_embedding_provider["baseUrl"]
        embedding_key_candidates = get_api_key_candidates(f"embedding:user:{current_user_id}", embedding_api_key)
    else:
        embedding_key_candidates = get_api_key_candidates("embedding", embedding_api_key, settings.get("apiKey"))
    if not embedding_key_candidates:
        embedding_key_candidates = [(0, 0, None)]

    main_logger.info(
        "HyperRAG API preflight start: "
        f"embedding_model={embedding_model}, embedding_base_url={embedding_base_url}, "
        f"llm_provider_pool={summarize_llm_provider_pool(settings)}, "
        f"embedding_key_pool={summarize_key_pool('embedding', embedding_api_key, settings.get('apiKey'))}"
    )

    embedding_errors = []
    embedding_ok = False
    for key_index, key_total, candidate_key in embedding_key_candidates:
        try:
            await openai_embedding(
                ["HyperRAG embedding preflight"],
                model=embedding_model,
                api_key=candidate_key,
                base_url=embedding_base_url,
                timeout=30.0,
            )
            embedding_ok = True
            main_logger.info(f"HyperRAG API preflight: embedding OK, key={key_index}/{key_total}")
            break
        except Exception as e:
            detailed_error = log_detailed_exception(
                main_logger,
                "HyperRAG API preflight failed - embedding",
                e,
                {
                    "key_index": key_index,
                    "key_total": key_total,
                    "embedding_model": embedding_model,
                    "embedding_base_url": embedding_base_url,
                    "runtime_settings": get_runtime_settings_context(),
                },
            )
            embedding_errors.append(detailed_error)
            if candidate_key:
                mark_api_key_unhealthy("embedding", candidate_key, detailed_error)
    if not embedding_ok:
        detail = " || ".join(embedding_errors)
        suggestion = extract_user_friendly_error(detail)
        raise RuntimeError(f"Embedding service preflight failed: {detail}. Suggestion: {suggestion}")

    user_llm_candidates = get_user_llm_provider_candidates(current_user_id, settings)
    if user_llm_candidates:
        llm_candidates = user_llm_candidates
    else:
        llm_candidates = get_llm_provider_candidates(settings)
    if not llm_candidates:
        raise RuntimeError("LLM service preflight failed: no healthy provider/key candidates")
    llm_errors = []
    llm_ok = False
    for candidate in llm_candidates:
        provider = candidate["provider"]
        try:
            await openai_complete_if_cache(
                provider.get("modelName"),
                "Reply exactly: OK",
                api_key=candidate.get("key"),
                base_url=provider.get("baseUrl"),
                timeout=30.0,
                max_tokens=8,
            )
            llm_ok = True
            main_logger.info(
                "HyperRAG API preflight: LLM OK, "
                f"provider={provider.get('name')}, key={candidate['key_index']}/{candidate['key_total']}"
            )
            break
        except Exception as e:
            detailed_error = log_detailed_exception(
                main_logger,
                "HyperRAG API preflight failed - LLM",
                e,
                {
                    "provider": provider.get("name"),
                    "key_index": candidate["key_index"],
                    "key_total": candidate["key_total"],
                    "model": provider.get("modelName"),
                    "base_url": provider.get("baseUrl"),
                    "runtime_settings": get_runtime_settings_context(),
                },
            )
            llm_errors.append(detailed_error)
            record_llm_provider_result(
                candidate,
                "fail",
                error_message=detailed_error,
                cooldown_seconds=_coerce_positive_int(settings.get("llmKeyCooldownSeconds", 60), 60),
            )
    if not llm_ok:
        detail = " || ".join(llm_errors)
        suggestion = extract_user_friendly_error(detail)
        raise RuntimeError(f"LLM service preflight failed: {detail}. Suggestion: {suggestion}")

def get_or_create_hyperrag(database: str = None, chunk_size: int = None, chunk_overlap: int = None):
    """
    闂傚倸鍊搁崐椋庣矆娓氣偓瀹曘儳鈧綆鍠栫壕鍧楁煙閹増顥夐幖鏉戯躬閺屻倝鎳濋幍顔肩墯婵炲瓨绮岀紞濠囧蓟濞戙垹唯妞ゆ梻鍘ч～鈺冪磽娴ｅ搫顎撶紓宥勭窔瀵鍨惧畷鍥ㄦ濡炪倖姊婚崢褔寮抽悢璁垮綊鎮埀顒勫矗閸愵喖绠栨俊銈呮噺閸婄兘鏌ｉ悢绋款棎闁稿鎸歌灃闁告侗鍘鹃敍鐔兼⒑闂堟稓澧曟繛鑼█瀹曟垿骞樼拠鎻掔€銈嗗姧缁插灝鈻撻妶澶嬧拺闂侇偆鍋涢懟顖涙櫠閸欏浜滄い鎰╁焺濡叉椽鏌涢悩璇у伐妞ゆ挸鍚嬪鍕節閸愵厾鍙戦梻鍌欒兌缁垰顫忔繝姘偍鐟滃繒鍒掓繝姘殤妞ゆ帒鍊婚敍婊堟⒑闂堟单鍫ュ疾濞嗘挸绠熷Δ锝呭暞閻?HyperRAG 闂傚倸鍊峰ù鍥敋瑜庨〃銉х矙閸柭も偓鍧楁⒑椤掆偓缁夊澹曠紒妯圭箚妞ゆ牗鑹鹃幃鎴炪亜?
    """
    global hyperrag_instances
    
    if not HYPERRAG_AVAILABLE:
        main_logger.error("Log message")
        raise RuntimeError("HyperRAG is not available")
    
    # 婵犵數濮烽弫鍛婃叏閻戝鈧倹绂掔€ｎ亞鍔﹀銈嗗坊閸嬫捇鏌涢悢閿嬪仴闁糕斁鍋撳銈嗗坊閸嬫挾绱撳鍜冭含妤犵偛鍟灒閻犲洩灏欑粣鐐寸節閻㈤潧浠ч柛瀣崌閹繝濮€閵堝棌鎷洪梺鍝勫€堕崕鎻掆枍閸涘瓨鐓曢柣鏇氱閻忥絿绱掗纰辩吋妤犵偞甯掕灃濞达絽鎼獮宥囩磽閸屾瑧顦︽い鎴濇閳ь剛鐟抽崶褏顔愰梺瑙勫婢ф鎮￠悢鍏肩叆婵犻潧妫Σ娲煟閿濆牊顏犻柍褜鍓氶鏍闯椤曗偓瀹曟垶绻濋崶褏鐣洪悷婊勬煥閻ｇ兘鎮℃惔妯绘杸闂佸壊鍋呯粙鎴炵娴煎瓨鈷掑ù锝呮啞鐠愶繝鏌涘Ο鐘叉处閸嬨倝鏌曟繛鐐珔缂佺姾顫夐妵鍕箛閳轰讲鍋撻弽顓ㄧ稏闁哄洨鍠撶弧鈧梻鍌氱墛缁嬫帗寰勯崟顐熸斀妞ゆ牗绋掔亸锕傛煙椤旇偐绉烘鐐扮窔楠炴帡骞嬪┑鎰偓鎾⒒娴ｅ憡鎯堟俊顐ｎ殘閹广垽骞囩敮顔剧◤濠德板€愰崑鎾绘煃閽樺妲搁柍璇查铻ｉ柣鎾抽姝囬梻鍌氬€搁崐宄懊归崶褜娴栭柕濞炬櫆閸ゅ嫰鏌ょ粙璺ㄤ粵婵炲懐濮垫穱濠囧Χ閸屾矮澹曢梻浣风串缁蹭粙鎮樺璺虹闁告侗鍨遍崰鍡涙煕閺囥劌浜滃┑?
    if database is None:
        database = db_manager.default_database
    # 濠电姷鏁告慨鐑姐€傞挊澹╋綁宕ㄩ弶鎴狅紱闂侀€炲苯澧撮柡灞剧〒閳ь剨缍嗛崑鍛暦瀹€鍕厸鐎光偓鐎ｎ剛锛熸繛瀵稿婵″洭骞忛悩璇茬闁圭儤鍩堝銉モ攽閻樻鏆柍褜鍓欓崯璺ㄧ棯瑜旈弻鐔碱敊閻撳簶鍋撻幖浣瑰仼闁绘垼妫勫敮闂佸啿鎼崐鐟扳枍閸ヮ剚鈷戦梺顐ゅ仜閼活垱鏅剁€电硶鍋撶憴鍕闁荤啿鏅犲顐㈩吋婢跺﹦顦伴梺闈涱焾閸庣増绔熼弴鐐╂斀闁绘劖娼欓悘锔姐亜韫囷絼閭い銏℃瀹曠喖骞嗛幍鍐蹭壕闁圭绨烘禍婊堢叓閸ャ劍灏版い銉у仱閹顫濋鐐叉懙闂佸搫鏈ú妯侯嚗閸曨偀妲堥柕蹇婃閳ь剙绉撮埞鎴︽倷閼碱剙顣洪梺缁樼墪閵堢顕ｆ繝姘亜闁绘挸瀛╁畵宥咁渻閵堝棙灏甸柛鐘虫尭閳绘捇濡舵径瀣ф嫽婵炶揪绲藉﹢鍗烇耿娴犲鐓曢柡鍌濇硶閻忛亶鏌嶈閸撴岸宕欒ぐ鎺戠闁绘梻鍘х粻鏍煕瑜庨〃鍛矆鐎ｎ偁浜滈柟鐑樺灥閳ь剙顭烽獮?
    requested_chunk_size = int(chunk_size) if chunk_size else None
    requested_chunk_overlap = int(chunk_overlap) if chunk_overlap is not None else None

    if database not in hyperrag_instances:
        main_logger.info("Log message")
        
        # 婵犵數濮烽弫鎼佸磻閻樿绠垫い蹇撴缁€濠囨煃瑜滈崜姘辨崲濞戞瑥绶為悗锝庡亞椤︿即鎮楀▓鍨珮闁稿锕ユ穱濠囨嚋闂堟稓绐炴繝鐢靛Т閸熶即鍩€椤掑澧存慨濠呮缁辨帒顫滈崱妯兼殽闂備胶绮〃鍛涘☉姘灊濠电姴娲﹂弲婵嬫煕鐏炵偓鐨戞い鏃€鍔欓弻锝嗘償閵忊懇濮囬柦鍐憾閹绠涢敐鍛睄闂佸搫鐬奸崰鏍€佸▎鎾村殟闁靛／灞拘為梻鍌欒兌閹虫捇宕查弻銉ョ疇閹兼番鍔夐埀顒婄畵婵℃悂鍩℃担鍝勫Е婵＄偑鍊栫敮鎺楀磹閸︻厸鍋撳顒夌吋闁哄矉缍佸顒€鈻庨悙顒傛瀮闂備礁鎽滈崰搴ㄥ箠濮椻偓瀵寮撮悢椋庣獮闂佸壊鍋呯缓楣冨磻閹炬緞鏃堝礃椤忓棛鍘┑鐘垫暩婵潙煤閿曞倹鍋傞柣鏂垮悑閻撳啴鏌涘┑鍡楊仼闁哄棛鍠栧畷陇绠涘☉娆屾嫽婵炶揪绲块幊鎾活敋濠婂懐纾奸悗锝庡亜閻忔挳鏌熼銊ユ搐楠炪垺绻涢幋鐐跺缂佷緤绠撳铏规喆閸曨偆顦ㄥ銈嗘肠閸涱垯绗?hgdb闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁撻悩鍐叉疄闂佽鍨奸悘鎰喆閸曞灚效闁瑰吋鐣崺鍕焽閻斿吋鈷戠痪顓炴噺瑜把囨⒒閸曨偄顏€?
        if database.endswith('.hgdb'):
            db_dir_name = database.replace('.hgdb', '')
        else:
            db_dir_name = database
            
        # HyperRAG 闂傚倷娴囬褍顫濋敃鍌︾稏濠㈣埖鍔曠粻鏍煕椤愶絾绀€缁炬儳娼￠弻鐔封枔閸喗鐏撶紓浣插亾濠电姴娲﹂悡娑㈡煕閹扳晛濡垮褎鐩弻娑欐償閳╁啯宕崇紓浣介哺閹告悂顢樻總绋垮窛妞ゆ牕鎲為崶銊у幍濡炪倖鐗楅懝楣冾敂椤愶附鐓冪憸婊堝礈濮樿京鐭欓柟鐑橆殕閺咁亜鈹戦悩顔肩伇婵炲绋撶划鏃堝箻椤旂晫鐣抽梻鍌欑劍鐎笛呮崲閸岀偞鍋嬪┑鐘插閸忔粓鏌涢锝嗙闁?hyperrag_cache 婵犵數濮烽弫鎼佸磻閻愬搫鍨傞柛顐ｆ礀缁犱即鏌熼梻瀵歌窗闁轰礁瀚伴弻娑㈠Ψ閹存柨浜鹃梺鍝勵儐濡啴寮婚悢鍛婄秶闁告挆鍛闂備礁鎼鍕濮樿泛钃熼柨婵嗘啒閺冨牆鐒垫い鎺戝閸嬪鏌涢埄鍐噮闁活厼鐗撻弻銊╁即閻愭祴鍋撻崫銉т笉鐟滅増甯楅崐鍨箾閹寸儐浼嗛柟瀵稿С閻掑﹤霉閻撳海鎽犻柣鎾寸洴閹鏁愭惔婵堢泿闂佸搫妫涢崑鐔烘閹烘纾兼繛鎴烆焽椤戝倿姊洪崷顓熷殌閻庢矮鍗抽悰顔界瑹閳ь剟鐛幒鎴悑闁搞儯鍔庤棟
        db_working_dir = os.path.join(hyperrag_working_dir, db_dir_name)
        Path(db_working_dir).mkdir(parents=True, exist_ok=True)
        
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            settings = json.load(f)

        embedding_dim = settings.get("embeddingDim")

        # 闂傚倸鍊搁崐椋庣矆娓氣偓瀹曘儳鈧綆鍠栫壕鍧楁煙閹増顥夐幖鏉戯躬閺屻倝鎳濋幍顔肩墯婵炲瓨绮岀紞濠囧蓟濞戙垹唯妞ゆ梹鍎崇敮銊х磽娴ｇ懓鏁剧紓宥勭窔瀵鈽夐姀鐘靛姶闂佸憡鍔楅崑鎾绘偩婵傚憡鈷戦柛娑橆煬閻掍粙鏌℃担绛嬪殭妞ゎ偄绻愮叅妞ゅ繐瀚鍥煟閻樺厖鑸柛鎾讳憾婵¤埖寰勭€ｎ剙骞?
        requested_domain = settings.get("hyperrag_domain", "default")
        experiment_mode = settings.get("experimentMode", settings.get("experiment_mode", "hyper_final"))
        try:
            from hyperrag.experiment import resolve_experiment_mode

            experiment_config = resolve_experiment_mode(
                experiment_mode,
                domain=requested_domain if requested_domain != "default" else "flow_battery",
            )
            for setting_key, config_key in [
                ("promptProfile", "prompt_profile"),
                ("prompt_profile", "prompt_profile"),
                ("enableEntityNormalization", "enable_entity_normalization"),
                ("enable_entity_normalization", "enable_entity_normalization"),
                ("enableMeasurementInstances", "enable_measurement_instances"),
                ("enable_measurement_instances", "enable_measurement_instances"),
                ("enableEfuRepair", "enable_efu_repair"),
                ("enable_efu_repair", "enable_efu_repair"),
                ("enableHybridRerank", "enable_hybrid_rerank"),
                ("enable_hybrid_rerank", "enable_hybrid_rerank"),
            ]:
                if setting_key in settings:
                    experiment_config[config_key] = settings[setting_key]
            current_domain = experiment_config.get("effective_domain", requested_domain)
        except Exception as e:
            main_logger.warning(f"Experiment mode resolution failed, using requested domain: {safe_str(e)}")
            experiment_config = {
                "experiment_mode": experiment_mode,
                "query_mode": "hyper",
                "prompt_profile": settings.get("promptProfile", settings.get("prompt_profile", "chemistry")),
                "domain": requested_domain,
                "effective_domain": requested_domain,
                "enable_entity_normalization": settings.get("enableEntityNormalization", settings.get("enable_entity_normalization", True)),
                "enable_measurement_instances": settings.get("enableMeasurementInstances", settings.get("enable_measurement_instances", True)),
                "enable_efu_repair": settings.get("enableEfuRepair", settings.get("enable_efu_repair", True)),
                "enable_hybrid_rerank": settings.get("enableHybridRerank", settings.get("enable_hybrid_rerank", True)),
            }
            current_domain = requested_domain
        main_logger.info(f"Using Hyper-RAG domain: {current_domain}, experiment={experiment_config.get('experiment_mode')}")

        # 婵犵數濮烽弫鍛婃叏閻戝鈧倹绂掔€ｎ亞鍔﹀銈嗗坊閸嬫捇鏌涢悢閿嬪仴闁糕斁鍋撳銈嗗坊閸嬫挾绱撳鍜冭含妤犵偛鍟灒閻犲洩灏欑粣鐐烘⒑瑜版帒浜伴柛鎾寸懃椤曪綁鏌ㄧ€ｎ剛鐦堥梺闈涢獜缂嶅棗顭囬幇鐗堝仺妞ゆ牗绮屾禒閬嶆煕閳规儳浜炬俊鐐€栫敮鎺楀窗濮橆剦鐒介柟閭﹀枓閸嬫捇宕楁径濠佸闂備礁缍婂Λ鍧楁倿閿曞倹鍋傞柡鍥ュ灪閻撳啴鏌涘┑鍡楊仼闁哄棙鐟︾换娑㈠川椤旂厧顫庣紓浣介哺鐢顭囪箛娑樜╃憸蹇涙偩婵傚憡鈷戦柣鐔告緲濡茬粯銇勯幋婵愭Ц闁伙絽鍢查…銊╁幢閳哄倐顒勬⒒娴ｅ憡鎯堟い鎴濇嚇瀹曟劕顫㈠畝鈧禍閬嶆⒒娴ｅ憡鎯堟い锔藉閳ь剛鐟抽崶浣割槸椤劑宕奸悢鍝勫箺闂備浇顫夐崕鎶筋敋椤撱垹绠犻柛娑卞灣绾惧吋銇勯弮鍌楁嫛闁绘挸銈搁弻鈩冩媴閸濄儛褏鈧娲滈崰鏍€佸Δ鍛劦妞ゆ帒瀚悞鍨亜閹烘垵鈧憡绂掗柆宥嗙厸?
        if current_domain != "default":
            try:
                from hyperrag.prompt import set_domain
                set_domain(current_domain)
                main_logger.info("Log message")
            except Exception as e:
                main_logger.warning("Log message")
                current_domain = "default"

        # 闂傚倸鍊搁崐椋庣矆娓氣偓瀹曘儳鈧綆鍠栫壕鍧楁煙閹増顥夐幖鏉戯躬閺屻倝鎳濋幍顔肩墯婵炲瓨绮岀紞濠囧蓟濞戙垹唯妞ゆ梹鍎崇敮銊х磽娴ｇ懓鏁剧紓宥勭窔瀵鈽夐姀鐘靛姶闂佸憡鍔楅崑鎾绘偩婵傚憡鈷戦柛娑橆煬閻掍粙鏌℃担鍓茬吋鐎殿喖顭烽弫鎰板川閸屾稒顥堢€规洘锕㈤崺鈩冩媴閸︻厽娈梻鍌氬€峰鎺旀椤斿墽绀婂ù锝堟娑撳秹鏌″搴″箹缂佺姵宀搁弻娑㈠箛闂堟稒鐏堢紓浣插亾閻庯綆鍋佹禍婊堟煙閹佃櫕娅呴柍褜鍓氶悧鏇⑩€﹂崸妤€鍐€闁靛ě鍜佸晭闂佸搫顦悧鍡樻櫠閻ｅ瞼鐭欏┑鐘崇閻撴瑧绱掔€ｎ亞浠㈤柍閿嬫閺岀喖顢氶崨顓熺彎濡炪們鍨哄ú鐔煎极閸愵喖鐒垫い鎺戝閸ㄥ倿鏌涘畝鈧崑鐐哄磹閻㈠憡鐓ユ繝闈涙閸ｈ銇勯敐鍛紞缂佽鲸甯￠崺鈧い鎺戝缁€瀣亜閹邦喖鏋戦柡鍌楀亾闂傚倷鑳堕崑銊╁磿闁秴鐤柛褎顨呴悞鍨亜閹哄棗浜剧紓鍌氱Т閿曨亪鐛崘銊庣喓鎷犻懠顒傜嵁闂備礁缍婇崑濠囧礈濞戙垹浼犳俊銈呮噺閻撶喖骞栨潏鍓х？濞寸姵绋掓穱濠囶敃閵忕姵娈婚悗?
        entity_types = None
        if current_domain != "default":
            try:
                from hyperrag.prompt import get_entity_types
                entity_types = get_entity_types(current_domain)
                main_logger.info("Log message")
            except Exception as e:
                main_logger.warning("Log message")

        # 闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁嶉崟顒佹濠德板€曢崯顖氱暦閺屻儲鐓曠€光偓閳ь剟宕戦悙鐑樺亗?HyperRAG 闂傚倸鍊峰ù鍥敋瑜庨〃銉х矙閸柭も偓鍧楁⒑椤掆偓缁夊澹曠紒妯圭箚妞ゆ牗鑹鹃幃鎴炪亜?
        hyperrag_kwargs = {
            "working_dir": db_working_dir,
            "llm_model_func": get_hyperrag_llm_func,
            "llm_model_stream_func": get_hyperrag_llm_stream_func,
            "llm_model_max_async": int(settings.get("llmGlobalMaxAsync", settings.get("llmModelMaxAsync", 4))),
            "embedding_func": EmbeddingFunc(
                embedding_dim=embedding_dim,  # text-embedding-3-small 闂傚倸鍊搁崐鐑芥倿閿曞倹鍎戠憸鐗堝笒缁€澶屸偓鍏夊亾闁逞屽墴閸┾偓妞ゆ帊绀侀崵顒勬煕閻樺磭澧崇憸棰佺椤啴濡堕崱姗嗘⒖婵犳鍠撻崐婵嗙暦?
                max_token_size=8192,
                func=get_hyperrag_embedding_func
            ),
                    "domain": current_domain,
            "experiment_mode": experiment_config.get("experiment_mode", "hyper_final"),
            "query_mode": experiment_config.get("query_mode", "hyper"),
            "prompt_profile": experiment_config.get("prompt_profile", "chemistry"),
            "enable_entity_normalization": bool(experiment_config.get("enable_entity_normalization", True)),
            "enable_measurement_instances": bool(experiment_config.get("enable_measurement_instances", True)),
            "enable_efu_repair": bool(experiment_config.get("enable_efu_repair", True)),
            "enable_hybrid_rerank": bool(experiment_config.get("enable_hybrid_rerank", True)),
        }

        if requested_chunk_size:
            hyperrag_kwargs["chunk_token_size"] = requested_chunk_size
        if requested_chunk_overlap is not None:
            hyperrag_kwargs["chunk_overlap_token_size"] = requested_chunk_overlap

        hyperrag_instances[database] = HyperRAG(**hyperrag_kwargs)

        # 婵犵數濮烽弫鎼佸磻閻斿澶愬箛閺夎法锛涢梺褰掑亰閸樺墽绮绘ィ鍐╃厓鐟滄粓宕滈悢鐓庤摕鐎广儱鐗滃銊╂⒑閸涘﹥灏版慨妯稿姂瀵偊顢氶埀顒勫极閹剧粯鍋愮€规洖娲ら獮鍫ユ⒒娴ｇ鏆遍柟纰卞亰瀹曨垶顢曢敃鈧崙鐘崇箾閹存瑥鐏柣鎾存礃娣囧﹪顢涘搴ｅ姼闂侀€炲苯澧い銊ョ墕鍗遍柟鐗堟緲缁秹鏌涢锝囩畺婵?HyperRAG 闂傚倸鍊峰ù鍥敋瑜庨〃銉х矙閸柭も偓鍧楁⒑椤掆偓缁夊澹曠紒妯圭箚妞ゆ牗鑹鹃幃鎴炪亜?
        if current_domain != "default":
            hyperrag_instances[database].domain = current_domain
        main_logger.info(
            f"HyperRAG effective config: database={database}, domain={hyperrag_instances[database].domain}, "
            f"chunk_token_size={hyperrag_instances[database].chunk_token_size}, "
            f"chunk_overlap_token_size={hyperrag_instances[database].chunk_overlap_token_size}, "
            f"llm_model_max_async={hyperrag_instances[database].llm_model_max_async}, "
            f"embedding_batch_num={hyperrag_instances[database].embedding_batch_num}"
        )
        
    else:
        main_logger.info("Log message")
    
    instance = hyperrag_instances[database]
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            settings = json.load(f)
        requested_domain = settings.get("hyperrag_domain", getattr(instance, "domain", "default"))
        experiment_mode = settings.get("experimentMode", settings.get("experiment_mode", getattr(instance, "experiment_mode", "hyper_final")))
        try:
            from hyperrag.experiment import resolve_experiment_mode

            experiment_config = resolve_experiment_mode(
                experiment_mode,
                domain=requested_domain if requested_domain != "default" else "flow_battery",
            )
            instance.domain = experiment_config.get("effective_domain", requested_domain)
            instance.experiment_mode = experiment_config.get("experiment_mode", getattr(instance, "experiment_mode", "hyper_final"))
            instance.query_mode = experiment_config.get("query_mode", getattr(instance, "query_mode", "hyper"))
            instance.prompt_profile = settings.get("promptProfile", settings.get("prompt_profile", experiment_config.get("prompt_profile", getattr(instance, "prompt_profile", "chemistry"))))
            instance.enable_entity_normalization = bool(settings.get("enableEntityNormalization", settings.get("enable_entity_normalization", experiment_config.get("enable_entity_normalization", True))))
            instance.enable_measurement_instances = bool(settings.get("enableMeasurementInstances", settings.get("enable_measurement_instances", experiment_config.get("enable_measurement_instances", True))))
            instance.enable_efu_repair = bool(settings.get("enableEfuRepair", settings.get("enable_efu_repair", experiment_config.get("enable_efu_repair", True))))
            instance.enable_hybrid_rerank = bool(settings.get("enableHybridRerank", settings.get("enable_hybrid_rerank", experiment_config.get("enable_hybrid_rerank", True))))
        except Exception:
            instance.domain = requested_domain
    except Exception as e:
        main_logger.warning("Log message")
    if requested_chunk_size:
        instance.chunk_token_size = requested_chunk_size
    if requested_chunk_overlap is not None:
        instance.chunk_overlap_token_size = requested_chunk_overlap
    main_logger.info(
        f"HyperRAG active config: database={database}, domain={getattr(instance, 'domain', 'default')}, "
        f"chunk_token_size={instance.chunk_token_size}, "
        f"chunk_overlap_token_size={instance.chunk_overlap_token_size}, "
        f"llm_model_max_async={instance.llm_model_max_async}, "
        f"embedding_batch_num={instance.embedding_batch_num}"
    )
    return instance


def get_or_create_cograg(database: str = None):
    """
    闂傚倸鍊搁崐椋庣矆娓氣偓瀹曘儳鈧綆鍠栫壕鍧楁煙閹増顥夐幖鏉戯躬閺屻倝鎳濋幍顔肩墯婵炲瓨绮岀紞濠囧蓟濞戙垹唯妞ゆ梻鍘ч～鈺冪磽娴ｅ搫顎撶紓宥勭窔瀵鍨惧畷鍥ㄦ濡炪倖姊婚崢褔寮抽悢璁垮綊鎮埀顒勫矗閸愵喖绠栨俊銈呮噺閸婄兘鏌ｉ悢绋款棎闁稿鎸歌灃闁告侗鍘鹃敍鐔兼⒑闂堟稓澧曟繛鑼█瀹曟垿骞樼拠鎻掔€銈嗗姧缁插灝鈻撻妶澶嬧拺闂侇偆鍋涢懟顖涙櫠閸欏浜滄い鎰╁焺濡叉椽鏌涢悩璇у伐妞ゆ挸鍚嬪鍕節閸愵厾鍙戦梻鍌欒兌缁垰顫忔繝姘偍鐟滃繒鍒掓繝姘殤妞ゆ帒鍊婚敍婊堟⒑闂堟单鍫ュ疾濞嗘挸绠熷Δ锝呭暞閻?Cog-RAG 闂傚倸鍊峰ù鍥敋瑜庨〃銉х矙閸柭も偓鍧楁⒑椤掆偓缁夊澹曠紒妯圭箚妞ゆ牗鑹鹃幃鎴炪亜?
    """
    global cograg_instances

    if not COGRAG_AVAILABLE:
        main_logger.error("Log message")
        raise RuntimeError("Cog-RAG is not available")

    # 婵犵數濮烽弫鍛婃叏閻戝鈧倹绂掔€ｎ亞鍔﹀銈嗗坊閸嬫捇鏌涢悢閿嬪仴闁糕斁鍋撳銈嗗坊閸嬫挾绱撳鍜冭含妤犵偛鍟灒閻犲洩灏欑粣鐐寸節閻㈤潧浠ч柛瀣崌閹繝濮€閵堝棌鎷洪梺鍝勫€堕崕鎻掆枍閸涘瓨鐓曢柣鏇氱閻忥絿绱掗纰辩吋妤犵偞甯掕灃濞达絽鎼獮宥囩磽閸屾瑧顦︽い鎴濇閳ь剛鐟抽崶褏顔愰梺瑙勫婢ф鎮￠悢鍏肩叆婵犻潧妫Σ娲煟閿濆牊顏犻柍褜鍓氶鏍闯椤曗偓瀹曟垶绻濋崶褏鐣洪悷婊勬煥閻ｇ兘鎮℃惔妯绘杸闂佸壊鍋呯粙鎴炵娴煎瓨鈷掑ù锝呮啞鐠愶繝鏌涘Ο鐘叉处閸嬨倝鏌曟繛鐐珔缂佺姾顫夐妵鍕箛閳轰讲鍋撻弽顓ㄧ稏闁哄洨鍠撶弧鈧梻鍌氱墛缁嬫帗寰勯崟顐熸斀妞ゆ牗绋掔亸锕傛煙椤旇偐绉烘鐐扮窔楠炴帡骞嬪┑鎰偓鎾⒒娴ｅ憡鎯堟俊顐ｎ殘閹广垽骞囩敮顔剧◤濠德板€愰崑鎾绘煃閽樺妲搁柍璇查铻ｉ柣鎾抽姝囬梻鍌氬€搁崐宄懊归崶褜娴栭柕濞炬櫆閸ゅ嫰鏌ょ粙璺ㄤ粵婵炲懐濮垫穱濠囧Χ閸屾矮澹曢梻浣风串缁蹭粙鎮樺璺虹闁告侗鍨遍崰鍡涙煕閺囥劌浜滃┑?
    if database is None:
        database = db_manager.default_database
    # 濠电姷鏁告慨鐑姐€傞挊澹╋綁宕ㄩ弶鎴狅紱闂侀€炲苯澧撮柡灞剧〒閳ь剨缍嗛崑鍛暦瀹€鍕厸鐎光偓鐎ｎ剛锛熸繛瀵稿婵″洭骞忛悩璇茬闁圭儤鍩堝銉モ攽閻樻鏆柍褜鍓欓崯璺ㄧ棯瑜旈弻鐔碱敊閻撳簶鍋撻幖浣瑰仼闁绘垼妫勫敮闂佸啿鎼崐鐟扳枍閸ヮ剚鈷戦梺顐ゅ仜閼活垱鏅剁€电硶鍋撶憴鍕闁荤啿鏅犲顐㈩吋婢跺﹦顦伴梺闈涱焾閸庣増绔熼弴鐐╂斀闁绘劖娼欓悘锔姐亜韫囷絼閭い銏℃瀹曠喖骞嗛幍鍐蹭壕闁圭绨烘禍婊堢叓閸ャ劍灏版い銉у仱閹顫濋鐐叉懙闂佸搫鏈ú妯侯嚗閸曨偀妲堥柕蹇婃閳ь剙绉撮埞鎴︽倷閼碱剙顣洪梺缁樼墪閵堢顕ｆ繝姘亜闁绘挸瀛╁畵宥咁渻閵堝棙灏甸柛鐘虫尭閳绘捇濡舵径瀣ф嫽婵炶揪绲藉﹢鍗烇耿娴犲鐓曢柡鍌濇硶閻忛亶鏌嶈閸撴岸宕欒ぐ鎺戠闁绘梻鍘х粻鏍煕瑜庨〃鍛矆鐎ｎ偁浜滈柟鐑樺灥閳ь剙顭烽獮?
    if database not in cograg_instances:
        main_logger.info("Log message")

        # 婵犵數濮烽弫鎼佸磻閻樿绠垫い蹇撴缁€濠囨煃瑜滈崜姘辨崲濞戞瑥绶為悗锝庡亞椤︿即鎮楀▓鍨珮闁稿锕ユ穱濠囨嚋闂堟稓绐炴繝鐢靛Т閸熶即鍩€椤掑澧存慨濠呮缁辨帒顫滈崱妯兼殽闂備胶绮〃鍛涘☉姘灊濠电姴娲﹂弲婵嬫煕鐏炵偓鐨戞い鏃€鍔欓弻锝嗘償閵忊懇濮囬柦鍐憾閹绠涢敐鍛睄闂佸搫鐬奸崰鏍€佸▎鎾村殟闁靛／灞拘為梻鍌欒兌閹虫捇宕查弻銉ョ疇閹兼番鍔夐埀顒婄畵婵℃悂鍩℃担鍝勫Е婵＄偑鍊栫敮鎺楀磹閸︻厸鍋撳顒夌吋闁哄矉缍佸顒€鈻庨悙顒傛瀮闂備礁鎽滈崰搴ㄥ箠濮椻偓瀵寮撮悢椋庣獮闂佸壊鍋呯缓楣冨磻閹炬緞鏃堝礃椤忓棛鍘┑鐘垫暩婵潙煤閿曞倹鍋傞柣鏂垮悑閻撳啴鏌涘┑鍡楊仼闁哄棛鍠栧畷陇绠涘☉娆屾嫽婵炶揪绲块幊鎾活敋濠婂懐纾奸悗锝庡亜閻忔挳鏌熼銊ユ搐楠炪垺绻涢幋鐐跺缂佷緤绠撳铏规喆閸曨偆顦ㄥ銈嗘肠閸涱垯绗?hgdb闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁撻悩鍐叉疄闂佽鍨奸悘鎰喆閸曞灚效闁瑰吋鐣崺鍕焽閻斿吋鈷戠痪顓炴噺瑜把囨⒒閸曨偄顏€?
        if database.endswith('.hgdb'):
            db_dir_name = database.replace('.hgdb', '')
        else:
            db_dir_name = database

        # Cog-RAG 闂傚倷娴囬褍顫濋敃鍌︾稏濠㈣埖鍔曠粻鏍煕椤愶絾绀€缁炬儳娼￠弻鐔封枔閸喗鐏撶紓浣插亾濠电姴娲﹂悡娑㈡煕閹扳晛濡垮褎鐩弻娑欐償閳╁啯宕崇紓?
        db_working_dir = os.path.join(cograg_working_dir, db_dir_name)
        Path(db_working_dir).mkdir(parents=True, exist_ok=True)

        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            settings = json.load(f)

        embedding_dim = settings.get("embeddingDim")

        # 闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁嶉崟顒佹濠德板€曢崯顖氱暦閺屻儲鐓曠€光偓閳ь剟宕戦悙鐑樺亗?Cog-RAG 闂傚倸鍊峰ù鍥敋瑜庨〃銉х矙閸柭も偓鍧楁⒑椤掆偓缁夊澹曠紒妯圭箚妞ゆ牗鑹鹃幃鎴炪亜閹邦亞鐭欓柡灞炬礃瀵板嫰宕卞Ο鑽ゅ絾闂備礁鎼幏瀣礈閻旂厧绠栨慨妞诲亾闁诡喗鐟╅獮宥夘敊閸撗冨箚闂傚倷娴囬鏍窗閺囩姴鍨濇繛鍡樺姃缁诲棙鎱ㄥ┑鍡欑劸婵¤尪宕电槐鎾存媴閸濆嫅锝夋煟閳哄﹤鐏︾€殿喖顭烽弫鎾绘偐閺屻儱鏁规繝鐢靛Т閻忔岸宕濋弽顭戞婵犵數濮烽弫鎼佸磻濞戙垺鍋嬪┑鐘叉搐閸屻劎绱掗埀顒€顫㈡笟鈧濠氬磼濞嗘埈妲梺纭咁嚋缁辨洟宕氶幒鎴犳殕闁告洦鍓欏▓锝咁渻閵堝棛澧紒顔奸叄閹矂宕奸妷锔惧幗闂侀潧绻堥崺鍕倿閸撗呯＜闁逞屽墴瀹曟帡鎮欑€电甯惧┑鐘灱濞夋盯鎮ч崱娑樼婵﹩鍘介崣蹇涙煥濠靛棙顥滃┑顔肩Ч閺?
        cograg_instances[database] = CogRAGClass(
            working_dir=db_working_dir,
            llm_model_func=get_hyperrag_llm_func,
            embedding_func=EmbeddingFunc(
                embedding_dim=embedding_dim,
                max_token_size=8192,
                func=get_hyperrag_embedding_func
            ),
        )

    else:
        main_logger.info("Log message")

    return cograg_instances[database]


class Message(BaseModel):
    message: str

@app.post("/process_message")
async def process_message(msg: Message, user: dict = Depends(require_current_user)):
    user_message = msg.message
    try:
        response_message = await get_hyperrag_llm_func(prompt=user_message)
    except Exception as e:
        return {"response": safe_str(e)} 
    return {"response": response_message}

# HyperRAG 闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾剧懓鈹戦悩瀹犲缂佺姵妞介弻锟犲炊閵夈儳浠鹃梺缁樻尵閸犳牠寮诲澶婁紶闁告洦鍋呴悘鎾绘⒑缂佹ê娴紒鐘崇墵瀵鈽夊Ο閿嬬€洪柣鐘叉搐瀵爼骞栭幇顔剧＜闁绘ê鍟块埢鏇㈡煛鐏炵偓绀冪€垫澘瀚板畷鐓庘攽閸℃娼涚紓?

class DocumentModel(BaseModel):
    content: str
    retries: int = 3
    database: str = None  # 濠电姷鏁告慨鐑藉极閹间礁纾块柟瀵稿Х缁€濠囨煃瑜滈崜姘跺Φ閸曨垰鍗抽柛鈩冾殔椤忣亪鏌涘▎蹇曠闁哄矉缍侀獮鍥敆娴ｇ懓鍓甸梻浣告惈椤戝嫮娆㈠璺鸿摕闁挎繂鎲橀弮鍫濈劦妞ゆ帒瀚崑瀣煕閳╁啰鎳呴柣顓炵墦閺屻劑寮撮悙娴嬪亾閸濄儳涓嶇憸鐗堝笚閸婂灚绻涢幋鐑嗕紗闁瑰濮抽悞濠冦亜閹捐泛袥闁稿鎸搁埢鎾诲垂椤旂晫褰梻浣告啞閹搁箖宕版惔顭戞晪?

class QueryModel(BaseModel):
    question: str
    mode: str = "hyper"  # 闂傚倸鍊搁崐宄懊归崶顒€违闁逞屽墴閺屾稓鈧綆鍋呭畷宀勬煙? hyper, hyper-lite, naive, graph, llm, cog, cog-hybrid, cog-entity, cog-theme
    top_k: int = 60
    max_token_for_text_unit: int = 1600
    max_token_for_entity_context: int = 300
    max_token_for_relation_context: int = 1600
    only_need_context: bool = False
    response_type: str = "Multiple Paragraphs"
    database: str = None  # 濠电姷鏁告慨鐑藉极閹间礁纾块柟瀵稿Х缁€濠囨煃瑜滈崜姘跺Φ閸曨垰鍗抽柛鈩冾殔椤忣亪鏌涘▎蹇曠闁哄矉缍侀獮鍥敆娴ｇ懓鍓甸梻浣告惈椤戝嫮娆㈠璺鸿摕闁挎繂鎲橀弮鍫濈劦妞ゆ帒瀚崑瀣煕閳╁啰鎳呴柣顓炵墦閺屻劑寮撮悙娴嬪亾閸濄儳涓嶇憸鐗堝笚閸婂灚绻涢幋鐑嗕紗闁瑰濮抽悞濠冦亜閹捐泛袥闁稿鎸搁埢鎾诲垂椤旂晫褰梻浣告啞閹搁箖宕版惔顭戞晪?

def normalize_query_result(result: Any) -> dict:
    """Normalize RAG query output so endpoints never call .get on None."""
    if result is None:
        return {"response": "", "entities": [], "themes": [], "hyperedges": [], "text_units": []}
    if isinstance(result, str):
        return {"response": result, "entities": [], "themes": [], "hyperedges": [], "text_units": []}
    if isinstance(result, dict):
        return {
            "response": result.get("response", ""),
            "entities": result.get("entities", []),
            "themes": result.get("themes", []),
            "hyperedges": result.get("hyperedges", []),
            "text_units": result.get("text_units", []),
        }
    return {"response": safe_str(result), "entities": [], "themes": [], "hyperedges": [], "text_units": []}


def resolve_public_demo_database() -> tuple[str | None, dict | None]:
    """Resolve the read-only public demo database."""
    configured = file_manager.sanitize_database_name(os.getenv("HYPERCHE_PUBLIC_DEMO_DATABASE", "public_example"))
    metadata = getattr(kb_manager, "_load_metadata", lambda: {})()

    configured_dir = os.path.join(hyperrag_working_dir, configured)
    if os.path.isdir(configured_dir):
        return configured, metadata.get(configured)
    if configured in metadata:
        return metadata[configured].get("database_name", configured), metadata[configured]

    for kb in metadata.values():
        if kb.get("name") == "example" or kb.get("database_name") == "example":
            return kb.get("database_name"), kb
    return None, None


def build_rag_query_response(query: QueryModel, result: Any, database: str, rag_system: str = "hyperrag") -> dict:
    normalized = normalize_query_result(result)
    payload = {
        "success": True,
        "response": normalized["response"],
        "entities": normalized["entities"],
        "hyperedges": normalized["hyperedges"],
        "text_units": normalized["text_units"],
        "mode": query.mode,
        "rag_system": rag_system,
        "question": query.question,
        "database": database or "default",
    }
    if normalized["themes"]:
        payload["themes"] = normalized["themes"]
    return payload


@app.post("/hyperrag/insert")
async def insert_document(doc: DocumentModel, user: dict = Depends(require_current_user)):
    """
    闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁嶉崟顐ｇ€抽悗骞垮劚椤︻垶宕归崒鐐寸厱闁规崘灏澶愭煕鐎ｎ偅宕岀€规洖缍婇、鏇㈡晲閸ヮ煈鍚囬梻鍌欑窔閳ь剛鍋涢懟顖涙櫠閸欏浜滄い鎰╁焺濡叉椽鏌涢悩璇у伐妞ゆ挸鍚嬪鍕節閸愵厾鍙戦梻鍌欒兌缁垰顫忔繝姘偍鐟滃繒鍒掓繝姘殤妞ゆ帒鍊婚敍婊堟⒑闂堟单鍫ュ疾濞嗘挸绠熷Δ锝呭暞閻?HyperRAG 闂傚倸鍊搁崐椋庣矆娴ｉ潻鑰块弶鍫氭櫅閸ㄦ繃銇勯弽銊х煁闁哄棙绮撻弻鐔兼倻濮楀棙鐣堕梺娲诲幗椤ㄥ﹪寮诲☉銏犵労闁告劦浜栧Σ鍫濃攽閳藉棗浜濋柨鏇樺灲瀵鈽夐姀鐘栥劑鏌ㄥ┑鍡樺櫣閹喖姊?
    """
    if not HYPERRAG_AVAILABLE:
        return {"success": False, "message": "HyperRAG is not available"}
    
    try:
        consume_document_quota_if_needed(user, 1)
        doc.database = namespace_database_name(doc.database, user)
        rag = get_or_create_hyperrag(doc.database)
        
        # 闂傚倸鍊搁崐鎼佸磹閻戣姤鍊块柨鏇氶檷娴滃綊鏌涢幇鍏哥敖闁活厽鎹囬弻锝夊箣閿濆憛鎾绘煕鎼粹槄鏀婚柕鍥у瀵粙顢曢～顓犳崟闂佽瀛╅懝楣兯囬悽绋胯摕婵炴垶菤閺€浠嬫煕閳╁喚娈㈠ù鐘层偢濮?
        for attempt in range(doc.retries):
            try:
                await rag.ainsert(doc.content)
                return {
                    "success": True, 
                    "message": "Document inserted successfully",
                    "database": doc.database or "default"
                }
            except Exception as e:
                if attempt == doc.retries - 1:
                    raise e
                print(f"Insert attempt {attempt + 1} failed: {e}. Retrying...")
                await asyncio.sleep(2)
                
    except Exception as e:
        return {"success": False, "message": f"Failed to insert document: {safe_str(e)}"}

@app.post("/hyperrag/query")
async def query_hyperrag(query: QueryModel, user: dict = Depends(require_current_user)):
    """
    缂傚倸鍊搁崐鎼佸磹閹间礁纾归柣鎴ｅГ閸ゅ嫰鏌涢锝嗙缂佹劖顨堥埀顒€绠嶉崕鍗灻洪妸鈺佺婵鍩栭悡娆戠磽娴ｉ潧鐏╅柡瀣枛閺屾稒鎯旈敍鍕懷囨煛鐏炲墽娲寸€殿喗鎸虫俊鎼佸Ψ閵夘喗楠勯梻鍌欑閹诧繝鎮烽姀銈呯；闁瑰墽绮埛鎴︽煠婵劕鈧洖鐡繝鐢靛仜閻即宕归挊澶屾殾閻熸瑥瀚弧鈧┑顔斤供閸橀箖宕㈡禒瀣拺鐟滅増甯掓禍浼存煕閻樻剚娈滄い銏℃閹垽鎼归崷顓ㄧ床闂佸搫顦悧鍕礉鎼达絿涓嶉柣鎰暯閸嬫挸鈻撻崹顔界亖闂佸憡鏌ㄩ柊锝夊春閳ь剚銇勯幒鍡椾壕闂佽绻戝畝鎼佺嵁濡ゅ懏鍊块柣鐐电┅rRAG闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁嶉崟顐㈢亰閻庡厜鍋撻柛鏇ㄥ墮娴犻亶姊虹悰鈥充壕闂?RAG濠电姷鏁告慨鐑姐€傞挊澹╋綁宕ㄩ弶鎴濈€銈呯箰閻楀棝鎮為崹顐犱簻闁瑰搫妫楁禍鍓х磼閸撗嗘闁告ɑ鍎抽埥澶愭偨缁嬭法鍔?
    """
    try:
        # 闂傚倸鍊峰ù鍥敋瑜嶉～婵嬫晝閸岋妇绋忔繝銏ｅ煐閸旀牠宕曞Δ浣典簻闁哄倸鐏濋埛鏂库槈閹惧磭效闁哄矉缍侀獮瀣偐閼碱兛绨礸-RAG濠电姷鏁告慨鐑姐€傞挊澹╋綁宕ㄩ弶鎴濈€銈呯箰閻楀棝鎮為崹顐犱簻闁瑰搫妫楁禍鍓х磼閸撗嗘闁告ɑ鍎抽埥澶愭偨缁嬭法鍔?
        cog_modes = ["cog", "cog-hybrid", "cog-entity", "cog-theme"]
        hyper_modes = ["hyper", "hyper-lite", "naive", "graph", "llm"]

        if query.mode in cog_modes:
            # 婵犵數濮烽弫鎼佸磻閻樿绠垫い蹇撴缁€濠囨煃瑜滈崜姘辨崲濞戞瑥绶為悗锝庡亞椤︿即鎮楀▓鍨珮闁稿锕ㄥΛ銏ゆ⒑閹稿孩绀冨ù?RAG
            if not COGRAG_AVAILABLE:
                return {"success": False, "message": "Cog-RAG is not available"}

            main_logger.info("Log message")
            query.database = require_database_access(query.database, user) if query.database else namespace_database_name("default", user)
            rag = get_or_create_cograg(query.database)

            # 闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁嶉崟顒佹濠德板€曢崯浼存儗濞嗘挻鐓欓悗鐢殿焾鍟哥紒鎯у綖缁瑩寮婚悢鐑樺珰闁圭粯甯為妶顦?RAG闂傚倸鍊搁崐椋庣矆娓氣偓楠炴牠顢曢妶鍡椾粡濡炪倖鍔х粻鎴犲閸ф鐓欑紓浣靛灩閺嬬喖鏌ｉ幘瀛樼缂佺粯鐩畷鍗炍旈崘顏嶅敹闂備線鈧偛鑻晶顔剧磽瀹ュ拑宸ユい?
            param = CogQueryParam(
                mode=query.mode,
                top_k=query.top_k,
                max_token_for_text_unit=query.max_token_for_text_unit,
                max_token_for_entity_context=query.max_token_for_entity_context,
                max_token_for_relation_context=query.max_token_for_relation_context,
                only_need_context=query.only_need_context,
                response_type=query.response_type,
            )

            # 闂傚倸鍊搁崐椋庣矆娴ｉ潻鑰块梺顒€绉甸崑锟犳煙閹増顥夋鐐灪缁绘盯骞嬮悜鍡欏姼闂佺濮ゅú鐔奉潖?
            result = await rag.aquery(query.question, param)

            # 婵犵數濮烽弫鍛婃叏娴兼潙鍨傞柣鎾崇岸閺嬫牗绻涢幋鐐茬劰闁稿鎸搁～婵嬫偂鎼淬垻褰庢俊銈囧Х閸嬫盯宕婊呯处濞寸姴顑呴悞鐢告煟閻愮數顩?RAG闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁嶉崟顒€搴婇梺绋挎湰缁酣鎯岄幘缁樺€甸柛顭戝亞閹藉啫鈹戦钘夆枙闁哄矉绱曟禒锔炬嫚閹绘帒顫撻梻浣告啞閸斿繘宕戦幘缁樷拻濞达綀娅ｇ敮娑㈡煙閸濄儺鐒鹃棁澶婎渻鐎ｎ亜顒㈤柛蹇旂矒閺?
            return {
                "success": True,
                "response": result.get("response", ""),
                "entities": result.get("entities", []),
                "themes": result.get("themes", []),  # Cog-RAG闂傚倸鍊搁崐鐑芥嚄閸撲礁鍨濇い鏍亼閳ь剙鍟鍕箛閸撲胶鈼ゅ┑鐘灱濞夋盯鈥﹂銏″殌闁割煈鍠撻埀顒佸笒椤繈鏁愰崨顒€顥氶梻鍌欐祰椤曟牠宕规导鏉戠柈闁哄鍨归弳锕傛煟閺冨倵鎷￠柡浣稿€块弻娑㈠即閵娿儱绠洪悶姘懄缁绘繄鍠婂Ο娲绘綉闂佺顑呭Λ娆撳疾鐠轰綍鏃堝礃閳哄啰鏆㈠┑鐘垫暩閸庢垹寰婇挊澹濇椽濡舵径瀣珖濡炪倕绻愰悧蹇撶暤?
                "hyperedges": result.get("hyperedges", []),
                "text_units": result.get("text_units", []),
                "mode": query.mode,
                "rag_system": "cograg",  # 闂傚倸鍊搁崐椋庣矆娓氣偓楠炴牠顢曢妶鍥╃厠闂佸搫顦伴崵姘洪鍕幐闂佸憡渚楅崰鏍礈閵娾晜鈷戦柣鐔煎亰閸ょ喖鏌涚€ｎ剙浠﹂柛鎺戯躬楠炴﹢顢欓挊澶夊寲闂備浇顕栭崢鐣屾暜閹烘挷绻嗗ù鐘差儐閻撴盯鏌涢埄鍐炬畼缂佺姴顭烽弻鈥崇暆鐎ｎ剛袦婵犵鍓濋幃鍌涗繆閻戣棄唯妞ゆ棁宕电壕濠氭⒒閸屾艾鈧娆㈤敓鐘茬獥闁哄稁鍙庨弫瀣亜閹捐泛校妞?
                "question": query.question,
                "database": query.database or "default"
            }

        elif query.mode in hyper_modes:
            # 婵犵數濮烽弫鎼佸磻閻樿绠垫い蹇撴缁€濠囨煃瑜滈崜姘辨崲濞戞瑥绶為悗锝庡亞椤︿即鎮楀▓鍨珮闁稿锕ユ穱濠囨嚋闂堟稓绐為柣搴秵娴滄瑩鎼规惔銊︹拻濞达綀娅ｇ敮娑欍亜閵娿儲鍤囬柟顔ㄥ嫮绡€闁告洦鍘虹粭澶愭⒑閸︻厼鍔嬫い銊ユ閹繝鎮㈤崗鑲╁帾婵犵數鍋涢悘婵嬪礉濮橆厾绠鹃柛顐犲灩閺嬩垢erRAG闂傚倸鍊搁崐鎼佸磹妞嬪孩顐介柨鐔哄Т绾惧鏌涘☉鍗炲福闁挎繂顦粻鎶芥煛閸愶絽浜惧?
            if not HYPERRAG_AVAILABLE:
                return {"success": False, "message": "HyperRAG is not available"}

            main_logger.info("Log message")
            query.database = require_database_access(query.database, user) if query.database else namespace_database_name("default", user)
            rag = get_or_create_hyperrag(query.database)
            param = QueryParam(
                mode=query.mode,
                top_k=query.top_k,
                max_token_for_text_unit=query.max_token_for_text_unit,
                max_token_for_entity_context=query.max_token_for_entity_context,
                max_token_for_relation_context=query.max_token_for_relation_context,
                only_need_context=query.only_need_context,
                response_type=query.response_type,
                return_type='json'
            )

            result = await rag.aquery(query.question, param)

            return {
                "success": True,
                "response": result.get("response", ""),
                "entities": result.get("entities", []),
                "hyperedges": result.get("hyperedges", []),
                "text_units": result.get("text_units", []),
                "mode": query.mode,
                "rag_system": "hyperrag",
                "question": query.question,
                "database": query.database or "default"
            }
        else:
            return {"success": False, "message": f"Unknown query mode: {query.mode}"}

    except Exception as e:
        main_logger.error("Log message")
        return {"success": False, "message": f"Query failed: {safe_str(e)}"}
        
    except Exception as e:
        return {"success": False, "message": f"Query failed: {safe_str(e)}"}

@app.post("/public/demo/query")
async def public_demo_query(query: QueryModel):
    """Read-only public demo query endpoint backed by the example chemical KB."""
    try:
        if query.mode not in ["hyper", "graph", "naive"]:
            query.mode = "hyper"
        if not HYPERRAG_AVAILABLE:
            return {"success": False, "message": "HyperRAG is not available"}

        database, kb = resolve_public_demo_database()
        if not database:
            return {
                "success": False,
                "message": "Public demo database is not configured. Set HYPERCHE_PUBLIC_DEMO_DATABASE or create an example KB.",
            }

        rag = get_or_create_hyperrag(database)
        if kb and kb.get("domain"):
            rag.domain = kb.get("domain")

        param = QueryParam(
            mode=query.mode,
            top_k=query.top_k,
            max_token_for_text_unit=query.max_token_for_text_unit,
            max_token_for_entity_context=query.max_token_for_entity_context,
            max_token_for_relation_context=query.max_token_for_relation_context,
            only_need_context=query.only_need_context,
            response_type=query.response_type,
            return_type='json'
        )
        result = await rag.aquery(query.question, param)
        payload = build_rag_query_response(query, result, database, "hyperrag")
        payload["demo"] = True
        payload["kb_name"] = kb.get("name") if kb else "example"
        payload["domain"] = getattr(rag, "domain", None)
        return payload

    except Exception as e:
        main_logger.error(f"Public demo query failed: {safe_str(e)}")
        return {"success": False, "message": f"Public demo query failed: {safe_str(e)}"}

@app.post("/public/demo/query/stream")
async def public_demo_query_stream(query: QueryModel):
    """Read-only public demo query endpoint with SSE streaming for Hyper-RAG answers."""
    async def event_stream():
        try:
            if query.mode not in ["hyper", "naive", "llm"]:
                yield f"event: error\ndata: {json.dumps({'message': 'Streaming currently supports hyper, naive, and llm modes only.'}, ensure_ascii=False)}\n\n"
                return
            if not HYPERRAG_AVAILABLE:
                yield f"event: error\ndata: {json.dumps({'message': 'HyperRAG is not available'}, ensure_ascii=False)}\n\n"
                return

            database, kb = resolve_public_demo_database()
            if not database:
                yield f"event: error\ndata: {json.dumps({'message': 'Public demo database is not configured.'}, ensure_ascii=False)}\n\n"
                return

            rag = get_or_create_hyperrag(database)
            if kb and kb.get("domain"):
                rag.domain = kb.get("domain")

            meta = {
                "success": True,
                "demo": True,
                "database": database,
                "kb_name": kb.get("name") if kb else "example",
                "domain": getattr(rag, "domain", None),
                "mode": query.mode,
            }
            yield f"event: meta\ndata: {json.dumps(meta, ensure_ascii=False)}\n\n"

            param = QueryParam(
                mode=query.mode,
                top_k=query.top_k,
                max_token_for_text_unit=query.max_token_for_text_unit,
                max_token_for_entity_context=query.max_token_for_entity_context,
                max_token_for_relation_context=query.max_token_for_relation_context,
                only_need_context=False,
                response_type=query.response_type,
                return_type='text'
            )
            async for token in rag.astream_query(query.question, param):
                yield f"event: token\ndata: {json.dumps({'text': token}, ensure_ascii=False)}\n\n"

            yield f"event: done\ndata: {json.dumps({'success': True}, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            main_logger.info("Public demo stream cancelled by client")
            raise
        except Exception as e:
            main_logger.error(f"Public demo stream failed: {safe_str(e)}")
            yield f"event: error\ndata: {json.dumps({'message': f'Public demo stream failed: {safe_str(e)}'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/hyperrag/status")
async def get_hyperrag_status(database: str = None):
    """
    闂傚倸鍊搁崐椋庣矆娓氣偓瀹曘儳鈧綆鍠栫壕鍧楁煙閹増顥夐幖鏉戯躬閺屻倝鎳濋幍顔肩墯婵炲瓨绮岀紞濠囧蓟濞戙垹唯妞ゆ梻鍘ч～鈺冪磽娴ｅ搫小闁告濞婂璇测槈閵忕姈銊╂煙鐎涙绠栭柛锝囧劋閹便劑鏁愰崨鏉戝及濠殿喖锕﹂崕銈咁焽椤忓牆绠悘鐐舵鐢垰鈹戦悩顐ｅ闁告洖鐏氶悾鍫曟⒑娴兼瑧鍒伴柣蹇斿哺楠炲繘宕ㄩ娑樻瀭闂佸憡娲﹂崑鍕繆閹惰姤鈷掑ù锝囩摂濞兼劗鈧娲橀敃銏犵暦濞差亜鍐€妞ゆ挾鍠庢禒?HyperRAG 闂傚倸鍊峰ù鍥敋瑜庨〃銉х矙閸柭も偓鍧楁⒑椤掆偓缁夊澹曠紒妯圭箚妞ゆ牗鑹鹃幃鎴炪亜閹邦亞鐭欓柡灞炬礃瀵板嫰宕卞Ο鑽ゅ絾闂備胶顭堥鍡涘礉濞嗘挸钃熼柕鍫濐槸娴肩娀鏌曟径妯烘灍婵絽鐭傚?
    """
    try:
        status = {
            "available": HYPERRAG_AVAILABLE,
            "database": database or "default",
            "working_dir": hyperrag_working_dir,
            "instances": list(hyperrag_instances.keys())
        }
        
        if database:
            # 闂傚倸鍊搁崐椋庣矆娓氣偓瀹曘儳鈧綆鍠栫壕鍧楁煙閹増顥夐幖鏉戯躬閺屻倝鎳濋幍顔肩墯婵炲瓨绮岀紞濠囧蓟濞戙垹唯妞ゆ梻鍘ч～顏堟⒑缁嬫鍎忔い鎴濐樀瀵鏁愭径瀣簻缂備礁顑嗛娆徫涢崱娑欌拺闁告繂瀚ˉ娆撴煕濡や礁鈻曠€殿喖顭烽崺鍕礃閳轰緡鈧捇姊洪崨濠勭畵閻庢氨鍏樺鎶筋敇閵忊€斥偓鐢告偡濞嗗繐顏悘蹇ｅ亰閺岋綁骞掗悙鐢垫殼濡ょ姷鍋涘Λ婵嗩嚕椤曗偓瀹曠厧鈹戦崼顐㈡櫔闂傚倷鑳堕崢褔骞楀鍫濇瀬闁归棿绀佸Ч鏌ユ煟濡偐甯涢柍閿嬪灩缁辨挻鎷呴惂闀愮返闂佺粯甯＄粻鏍蓟濞戙垹鐓涢柛灞剧矊閳峰矂姊虹化鏇熸澒闁?
            if database in hyperrag_instances:
                instance = hyperrag_instances[database]
                status["initialized"] = True
                try:
                    status["details"] = {
                        "chunk_token_size": instance.chunk_token_size,
                        "llm_model_name": instance.llm_model_name,
                        "embedding_func_available": instance.embedding_func is not None,
                        "working_dir": os.path.join(hyperrag_working_dir, database.replace('.hgdb', ''))
                    }
                except Exception as e:
                    status["details"] = f"Error getting details: {safe_str(e)}"
            else:
                status["initialized"] = False
        else:
            # 闂傚倸鍊搁崐椋庣矆娓氣偓瀹曘儳鈧綆鍠栫壕鍧楁煙閹増顥夐幖鏉戯躬閺屻倝鎳濋幍顔肩墯婵炲瓨绮岀紞濠囧蓟濞戙垹唯妞ゆ梻鍘ч～鈺冪磽娴ｅ搫袨闁稿海鏁诲璇差吋閸偅顎囬梻浣告啞閹搁箖宕版惔顭戞晪闁挎繂顦崹鍌涖亜閹扳晛鐏紒鎰仦缁绘繈鎮介棃娴躲垽鎮楀鐓庡箹妞ゎ厼娼″浠嬪Ω瑜忛鏇㈡⒑閻熸澘鈷旀い銉﹀姈缁旂喎螣濮瑰洣绨婚梺鐟扮摠缁诲啴骞栭幇鐗堢厓缂備焦蓱瀹曞本顨ラ悙宸剰闁宠鍨块獮鍥敇閻愮増妯婇梻?
            status["initialized"] = len(hyperrag_instances) > 0
            status["total_instances"] = len(hyperrag_instances)
        
        return status

    except Exception as e:
        return {"success": False, "message": f"Failed to get status: {safe_str(e)}"}

@app.post("/cograg/insert")
async def insert_cograg_document(doc: DocumentModel):
    """
    闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁嶉崟顐ｇ€抽悗骞垮劚椤︻垶宕归崒鐐寸厱闁规崘灏澶愭煕鐎ｎ偅宕岀€规洖缍婇、鏇㈡晲閸ヮ煈鍚囬梻鍌欑窔閳ь剛鍋涢懟顖涙櫠閸欏浜滄い鎰╁焺濡叉椽鏌涢悩璇у伐妞ゆ挸鍚嬪鍕節閸愵厾鍙戦梻鍌欒兌缁垰顫忔繝姘偍鐟滃繒鍒掓繝姘殤妞ゆ帒鍊婚敍婊堟⒑闂堟单鍫ュ疾濞嗘挸绠熷Δ锝呭暞閻?Cog-RAG 闂傚倸鍊搁崐椋庣矆娴ｉ潻鑰块弶鍫氭櫅閸ㄦ繃銇勯弽銊х煁闁哄棙绮撻弻鐔兼倻濮楀棙鐣堕梺娲诲幗椤ㄥ﹪寮诲☉銏犵労闁告劦浜栧Σ鍫濃攽閳藉棗浜濋柨鏇樺灲瀵鈽夐姀鐘栥劑鏌ㄥ┑鍡樺櫣閹喖姊?
    """
    if not COGRAG_AVAILABLE:
        return {"success": False, "message": "Cog-RAG is not available"}

    try:
        rag = get_or_create_cograg(doc.database)

        # 闂傚倸鍊搁崐鎼佸磹閻戣姤鍊块柨鏇氶檷娴滃綊鏌涢幇鍏哥敖闁活厽鎹囬弻锝夊箣閿濆憛鎾绘煕鎼粹槄鏀婚柕鍥у瀵粙顢曢～顓犳崟闂佽瀛╅懝楣兯囬悽绋胯摕婵炴垶菤閺€浠嬫煕閳╁喚娈㈠ù鐘层偢濮?
        for attempt in range(doc.retries):
            try:
                await rag.ainsert(doc.content)
                main_logger.info("Log message")
                return {
                    "success": True,
                    "message": "Document inserted into Cog-RAG successfully",
                    "database": doc.database or "default",
                    "rag_system": "cograg"
                }
            except Exception as e:
                if attempt == doc.retries - 1:
                    raise e
                main_logger.warning("Log message")
                await asyncio.sleep(2)

    except Exception as e:
        main_logger.error("Log message")
        return {"success": False, "message": f"Failed to insert document into Cog-RAG: {safe_str(e)}"}

@app.get("/cograg/status")
async def get_cograg_status(database: str = None):
    """
    闂傚倸鍊搁崐椋庣矆娓氣偓瀹曘儳鈧綆鍠栫壕鍧楁煙閹増顥夐幖鏉戯躬閺屻倝鎳濋幍顔肩墯婵炲瓨绮岀紞濠囧蓟濞戙垹顫呴柣姗€娼у绺?RAG闂傚倸鍊峰ù鍥敋瑜庨〃銉х矙閸柭も偓鍧楁⒑椤掆偓缁夊澹曠紒妯圭箚妞ゆ牗鑹鹃幃鎴炪亜閹邦亞鐭欓柡灞炬礃瀵板嫰宕卞Ο鑽ゅ絾闂備胶顭堥鍡涘礉濞嗘挸钃熼柕鍫濐槸娴肩娀鏌曟径妯烘灍婵絽鐭傚?
    """
    try:
        status = {
            "available": COGRAG_AVAILABLE,
            "database": database or "default",
            "working_dir": cograg_working_dir,
            "instances": list(cograg_instances.keys())
        }

        if database and database in cograg_instances:
            instance = cograg_instances[database]
            status["initialized"] = True
            status["details"] = {
                "chunk_token_size": instance.chunk_token_size,
                "llm_model_name": instance.llm_model_name,
                "embedding_func_available": instance.embedding_func is not None,
                "working_dir": os.path.join(cograg_working_dir, database.replace('.hgdb', ''))
            }
        else:
            status["initialized"] = False

        return status
    except Exception as e:
        main_logger.error("Log message")
        return {"success": False, "message": f"Failed to get Cog-RAG status: {safe_str(e)}"}

@app.get("/systems/status")
async def get_systems_status():
    """
    闂傚倸鍊搁崐椋庣矆娓氣偓瀹曘儳鈧綆鍠栫壕鍧楁煙閹増顥夐幖鏉戯躬閺屻倝鎳濋幍顔肩墯婵炲瓨绮岀紞濠囧蓟濞戙垹唯妞ゆ梻鍘ч～鈺冪磽娴ｅ搫袨闁稿海鏁诲璇差吋閸偅顎囬梻浣告啞閹搁箖宕版惔顭戞晪闁挎繂顦崹鍌涖亜閹扳晛鈧鎮炬禒瀣拺闁告繂瀚弳鐔兼煟閹炬椿妫戠紒杈ㄦ崌瀹曟帒鈻庨幋锝囩崶闂備焦鎮堕崝鎴濐焽瑜旈幃楣冩倻閼恒儱浠洪梻鍌氱墛缁嬫垿鎮樻繝鍌楁斀闁绘劕寮堕埢鏇灻瑰鍕疄鐎规洘娲栭鍏煎緞鐎ｎ剙骞堥梻浣告惈濞层垽宕濆畝鍕祦闁哄稁鍋嗙粻鏃堟煙鏉堥箖妾柍?
    """
    try:
        status = {
            "hyperrag": {
                "available": HYPERRAG_AVAILABLE,
                "instances": len(hyperrag_instances),
                "working_dir": hyperrag_working_dir
            },
            "cograg": {
                "available": COGRAG_AVAILABLE,
                "instances": len(cograg_instances),
                "working_dir": cograg_working_dir
            },
            "current_system": "hyperrag"  # 婵犵數濮甸鏍窗濡ゅ啯鏆滄俊銈呭暟閻瑩鏌熼悜妯镐粶闁逞屽墾缁犳挸鐣锋總绋款潊闁靛浚婢佺槐鍙変繆閻愵亜鈧牠鎮уΔ鍐╁床闁稿瞼鍋涚憴锕傛煕閿旇骞樼痪?
        }
        return status
    except Exception as e:
        main_logger.error("Log message")
        return {"success": False, "message": f"Failed to get systems status: {safe_str(e)}"}

@app.delete("/hyperrag/reset")
async def reset_hyperrag(database: str = None):
    """
    闂傚倸鍊搁崐鎼佸磹閻戣姤鍊块柨鏇氶檷娴滃綊鏌涢幇鍏哥敖闁活厽鎹囬弻娑㈩敃閿濆棛顦ㄩ梺绋款儛娴滎亪寮诲☉銏犵労闁告劦浜栧Σ鍫㈢磽娴ｅ搫小闁告濞婂璇测槈閵忕姈銊╂煙鐎涙绠栭柛锝囧劋閹便劑鏁愰崨鏉戝及濠殿喖锕﹂崕銈咁焽椤忓牆绠悘鐐舵鐢垰鈹戦悩顐ｅ闁告洖鐏氶悾鍫曟⒑娴兼瑧鍒伴柣蹇斿哺楠炲繘宕ㄩ娑樻瀭闂佸憡娲﹂崑鍕繆閹惰姤鈷掑ù锝囩摂濞兼劗鈧娲橀敃銏犵暦濞差亜鍐€妞ゆ挾鍠庢禒?HyperRAG 闂傚倸鍊峰ù鍥敋瑜庨〃銉х矙閸柭も偓鍧楁⒑椤掆偓缁夊澹曠紒妯圭箚妞ゆ牗鑹鹃幃鎴炪亜閹邦亞鐭欓柡灞炬礃瀵板嫰宕卞Ο鑽ゅ絾闂備礁鎼幏瀣礈閻旂厧绠栨慨妞诲亾闁诡喗鐟╁鍫曞箣濠靛柊鎴︽⒒娴ｇ瓔鍤欑紒缁樺灴閵嗗啯绻濋崒銈嗙稁濠电偛妯婃禍婊呯不閻㈠憡鐓欓柣鎴炆戦悘娑㈡煏閸繍妲归柣鎾跺枛閺屾洟宕煎┑鍥ф濡炪們鍎崹娲€冮妷鈺傚€烽柤纰卞劮瑜旈弻娑㈠煘閹傚濠碉紕鍋戦崐鏍暜閹烘柡鍋撳鐓庡闁逞屽墯閼归箖藝椤栫偐鈧妇鎹勯妸锕€纾梺缁樼濞兼瑦鎱ㄥ☉銏♀拺闁告繂瀚峰Σ鍏间繆椤愩垹顏┑?
    """
    global hyperrag_instances
    
    try:
        if database:
            # 闂傚倸鍊搁崐鎼佸磹閻戣姤鍊块柨鏇氶檷娴滃綊鏌涢幇鍏哥敖闁活厽鎹囬弻娑㈩敃閿濆棛顦ㄩ梺绋款儛娴滎亪寮诲☉銏犵労闁告劦浜栨慨鍥⒑缁嬫鍎忔い鎴濐樀瀵鏁愭径瀣簻缂備礁顑嗛娆徫涢崱娑欌拺闁告繂瀚ˉ娆撴煕濡や礁鈻曠€殿喖顭烽崺鍕礃閳轰緡鈧捇姊洪崨濠勭畵閻庢氨鍏樺鎶筋敇閵忊€斥偓鐢告偡濞嗗繐顏悘蹇ｅ亰閺岋綁骞掗悙鐢垫殼濡ょ姷鍋涘Λ婵嗩嚕椤曗偓瀹曠厧鈹戦崼顐㈡櫔闂傚倷鑳堕崢褔骞楀鍫濇瀬闁归棿绀佸Ч鏌ユ煟濡偐甯涢柣鎾跺枛楠炴牜鍒掗悷鏉库拤闁荤姵鍔х换婵嬪蓟濞戞埃鍋撻敐搴′航闁绘帟濮ょ换?
            if database in hyperrag_instances:
                del hyperrag_instances[database]
                return {
                    "success": True, 
                    "message": f"HyperRAG instance for database '{database}' reset successfully"
                }
            else:
                return {
                    "success": False, 
                    "message": f"No HyperRAG instance found for database '{database}'"
                }
        else:
            # 闂傚倸鍊搁崐鎼佸磹閻戣姤鍊块柨鏇氶檷娴滃綊鏌涢幇鍏哥敖闁活厽鎹囬弻娑㈩敃閿濆棛顦ㄩ梺绋款儛娴滎亪寮诲☉銏犵労闁告劦浜栧Σ鍫㈢磽娴ｅ搫袨闁稿海鏁诲璇差吋閸偅顎囬梻浣告啞閹搁箖宕版惔顭戞晪闁挎繂顦崹鍌涖亜閹扳晛鐏紒鎰仦缁绘繈鎮介棃娴躲垽鎮楀鐓庡箹妞ゎ厼娼″浠嬪Ω瑜忛?
            hyperrag_instances = {}
            return {"success": True, "message": "All HyperRAG instances reset successfully"}
            
    except Exception as e:
        return {"success": False, "message": f"Failed to reset: {safe_str(e)}"}

# 闂傚倸鍊搁崐椋庣矆娓氣偓楠炴牠顢曢敃鈧壕鍦磼鐎ｎ偓绱╂繛宸簼閺呮煡鏌涘☉鍙樼凹闁诲骸顭峰娲濞戞氨鐤勯梺鎼炲妿缁垳绮欐径濠庡悑濠㈣泛顑囬崣鍡椻攽閻愭潙鐏﹂柨姘亜韫囷絼閭柡灞剧⊕缁绘繈宕熼鈩冾潟闂備礁鎼惌澶岀礊娓氣偓瀹曟椽鏁撻悩鑼槰闂佸憡鎸嗛崘銊愵亪姊婚崒娆戭槮闁硅绻濋、鏃堝箹娴ｅ摜鍊為梺闈涱焾閸庤鲸绔熼崟顖涒拻濞达絽鎲￠崯鐐烘煕閵娿儳鍩ｉ柛鈺冨仦缁鸿棄顓兼径瀣ф嫽婵炶揪绲块悺鏂款焽閹邦優鐟邦煥閳ь剛鍒掑▎蹇曟殾闁哄洨鍠愮紞鍥ㄣ亜閹邦喖小婵?

class FileEmbedRequest(BaseModel):
    file_ids: List[str]
    chunk_size: int = 500  # 闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁撻悩鎻掔€梺姹囧灩閻忔艾鐣烽弻銉︾厵闁规鍠栭。濂告煕鎼达紕效闁哄矉缍侀幃婊堝幢濡搫褰檜nk_size闂傚倸鍊搁崐鎼佸磹妞嬪孩顐介柨鐔哄Т缁€鍫熺箾閸℃ɑ灏伴柛濠呭煐缁绘繈妫冨☉鍗炲壈闂佺琚崝鎴﹀蓟閺囥垹閱囨繝闈涙搐椤︹晠姊虹拠鈥崇仜闁稿海鏁诲璇测槈濡攱顫嶉梺鍛婎殘閸嬬偤鎮樺鍜佹富?
    chunk_overlap: int = 100  # 闂傚倸鍊搁崐鐑芥嚄閸洖纾块柣銏㈩焾閻ょ偓绻濋棃娑卞剬闁逞屽墾缁犳挸鐣锋總绋款潊闁挎繂鎲涢敓鐘斥拺闁告繂瀚～锕傛煕鎼淬倓鍚紒顔肩墦瀹曠喖顢涘鍐ㄧ导闂備焦鎮堕崕顖炲礉瀹ュ洣鐒婇柛顭戝亝閸欏繘鏌ㄥ┑鍡樺櫤闂傚嫬鎾rlap
    rag_system: str = "hyperrag"  # 闂傚倸鍊搁崐椋庣矆娓氣偓楠炴牠顢曢敃鈧壕褰掓煟閻旂厧浜伴柣鏂挎閹便劌顪冪拠韫闂備礁鎼悮顐﹀礉瀹€鍕叀濠㈣泛艌閺嬪酣鐓崶銊﹀鞍闁硅櫕鐟╁缁樼瑹閳ь剟鍩€椤掑倸浠滈柤娲诲灡閺呭爼顢欐慨鎰盎闂佹寧妫佸Λ鍕夌€ｎ喗鐓冪憸婊堝礈濮樿泛鏄ラ柛鎰ㄦ櫆濞呯姷绱掓潏鈺娾偓搴ｇ磽閸屾艾鈧悂宕愭搴㈩偨闁跨喓濮撮崹鍌炴⒒閸喓銆掗柡鍡畵閺岋綁濮€閵堝棙閿梺?(hyperrag 闂?cograg)
    target_database: Optional[str] = None  # 闂傚倸鍊搁崐鐑芥嚄閸洖纾块柣銏㈩焾閻ょ偓绻濋棃娑卞剰闁搞劌鍊搁埞鎴﹀磼濮橆厼鏆堥梺缁樻尰缁嬫垿婀侀梺鎸庣箓閹冲繘骞嗛崼鐔翠簻闁挎繂鐗嗘禍褰掓煃瑜滈崜婵嬶綖婢舵劕绠伴柣鎴ｅГ閸婂潡鏌ㄩ弴鐐测偓鍝ョ不濮樿埖鐓涢柛鎰╁妿婢ф洜绱掗悩宸吋闁哄睙鍡欑杸闁挎繂鎳嶇花濠氭⒑闁偛鑻晶顔剧棯缂併垹骞樻俊鍙夊姍楠炴帡骞樺畷鍥╃嵁濠电姷鏁告慨鎾磹婵犳碍鍎庨幖杈剧悼绾捐棄霉閿濆嫮鐭欓柛婵婃缁辨帗娼忛妸銉︽殬ne闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁嶉崟顒佹濠德板€曢幊蹇涘磻閿熺姵鐓忛柛顐ｇ箖椤ョ姷绱掗悩鑽ょ暫闁哄本鐩俊鐑筋敊閻撳寒娼介梻浣侯焾椤戝啴宕濋幋锕€钃熼柡鍥╁枔缁♀偓闂婎偄娲︾粙鎺楊敁瀹ュ鈷戦悹鍥ㄥ絻閻︺劑鏌涢悩宕囧⒌婵犫偓娓氣偓濮婅櫣绱掑鍡欏姺闂佺绨洪崐妤€鈽夐崹顐犲亝闁告劏鏅濋崢鍗炩攽閻愬弶鍤€妞ゆ泦鍏犳椽鏁冮崒姘優闂佺鐬奸崑鐐烘偂濞戙垺鐓曢柟鎵虫櫅婵″ジ鏌嶈閸撴瑧绱炴繝鍥х畺濡わ絽鍟悞鑲┾偓骞垮劚濡盯宕㈤崨濠勭閺夊牆澧介崚浼存煙绾板崬浜伴柕鍡楀€块幊鏍煘閹傚闁荤喐鐟ョ€氼厾浜搁锔界厽闁硅櫣鍋熼悾鍨殽?
    update_file_database: bool = False  # 闂傚倸鍊搁崐椋庣矆娓氣偓楠炴牠顢曢妶鍌氫壕婵鍘у顔锯偓瑙勬礃濞叉鎹㈠┑瀣倞闁靛ě鍐ㄧ闂傚倷鐒﹂幃鍫曞磿濠婂牆宸濇い鏃囨閺嬫盯姊婚崒娆戭槮闁圭⒈鍋婇幊鐔碱敍閻愬瓨娅囧銈呯箰鐎氱兘宕甸弴鐔翠簻闁圭儤鍨甸鈺呮煟閹邦剨韬柡灞诲姂瀵噣宕掑鍕晵闂備胶顭堥鍐礉閹存繍娼栭柧蹇撴贡閻瑩鎮归幁鎺戝妞ゆ柨娲鍝勑ч崶褉鍋撻弴鐏绘椽鏁傞崜褏鐒块梺鍦劋椤ㄥ懘鏌嬮崶顒佺厪濠㈣埖绋撻悾閬嶆煕閹垮啫寮慨濠冩そ瀹曘劍绻濋崘顭戞П闂備礁鎲￠幐濠氭嚌妤ｅ啫鐓濋柟鎹愵嚙闁卞洭鏌￠崶鈺佹灁闁告鏁诲娲閳轰胶妲ｉ梺鍛娒肩划娆撳箚?
    kb_name: Optional[str] = None  # 闂傚倸鍊搁崐鐑芥倿閿曗偓椤啴宕稿Δ鈧崒銊ф喐閻楀牆绗掔痪鎯ф健閺岀喓绱掗姀鐘崇亶闂佺楠搁敃顏堝蓟閻旇　鍋撻悽娈跨劸濞寸媴绠撻弻娑欐償閿濆懏鐏堥梺鍝勭灱閸犳牠鐛幋锕€绠涙い鎾跺Т濞懷囨⒒娴ｄ警鐒鹃柨鏇樺€楁竟鏇㈩敇閻樻剚娼熼梺鍦劋閹稿摜娆㈤悙娴嬫斀闁绘ɑ褰冮埀顒€顭烽幆鍕償閿濆洨锛濇繛杈剧导缁瑩宕搹鍦＜閻犲洩灏欐晶锔筋殽閻愯宸ラ柍钘夘槸閳诲酣骞囬鈧导搴ㄦ⒒娴ｇ鏆遍柟纰卞亰瀹曟劙鎳￠妶鍥︾瑝濠电偛妫欓幐濠氭偂閺囩喍绻嗘い鏍ㄧ箓閸氱懓顭胯娴滎亪寮婚敐澶嬫櫜闁搞儯鍔嶅В鍕箾鐎电顎撶紒鐘虫崌楠炴劖绻濋崘銊х獮婵犵數濮撮崯宕囨閵忋倖鈷掗柛灞捐壘閳ь剛鍏橀幃鐐烘晝閳ь剟鈥﹂崹顔ョ喖鎳栭埡鍐帬闂備礁澹婇崑鍛哄鈧畷?

@app.get("/files")
async def get_files(user: dict = Depends(require_current_user)):
    """
    闂傚倸鍊搁崐椋庣矆娓氣偓瀹曘儳鈧綆鍠栫壕鍧楁煙閹増顥夐幖鏉戯躬閺屻倝鎳濋幍顔肩墯婵炲瓨绮岀紞濠囧蓟濞戙垹唯妞ゆ梻鍘ч～鈺冪磽娴ｅ搫袨闁稿海鏁诲璇差吋閸偅顎囬梻浣告啞閹搁箖宕版惔顭戞晪闁挎繂顦崹鍌涖亜閹扳晛鐏紒鎰仦缁绘繈濮€閿濆棛銆愰梺娲诲墮閵堟悂鐛径鎰垫晜闁告侗鍨抽鏇犵磼閻愵剙鍔ゆい鎴濇噺缁傚秹鎮烽幍铏杸濡炪倖姊婚崢褍危婵犳碍鐓冪紓浣股戝畷灞绢殽閻愬樊鍎旈柡浣稿暣閸┾偓妞ゆ巻鍋撻摶鐐存叏濡炶浜鹃梺鍝勬湰閻╊垱淇婇悜绛嬫晬闁绘劖鎯岄埀顒€绉撮—鍐Χ閸℃顫堢紓渚囧枟閻熲晛顕ｇ拠娴嬫闁靛繒濮烽濠囨⒑閻熸壆浠㈤柛鐕佸灦閹偓绂掔€ｎ偀鎷?
    """
    try:
        files = file_manager.get_all_files(owner_user_id=user.get("id"), include_legacy=True)
        return {"files": files}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/files/upload")
async def upload_files(
    files: List[UploadFile] = File(...),
    target_database: str = Form(default=None),
    kb_name: str = Form(default=None),
    user: dict = Depends(require_current_user)
):
    """
    婵犵數濮烽弫鎼佸磻閻愬搫鍨傞柛顐ｆ礀缁犱即鏌熼梻瀵稿妽闁哄懏绻堥弻銊モ攽閸℃ê顦╁銈庡亝濞茬喖寮诲☉銏╂晝闁挎繂妫涢ˇ銉モ攽閳藉棗浜濋柨鏇樺灲瀵鈽夐姀鐘栥劍銇勯弽顐沪妞ゅ骸绉撮—鍐Χ閸℃顫堢紓渚囧枟閻熲晛顕ｆ繝姘亜闁绘挸娴烽悾鎶芥⒑閸︻厼鍔嬮柛銊ョ仛閹便劍鎯旈妸锕€浠?

    Args:
        files: 婵犵數濮烽弫鎼佸磻閻愬搫鍨傞柛顐ｆ礀缁犱即鏌熼梻瀵稿妽闁哄懏绻堥弻銊モ攽閸℃ê顦╁銈庡亝濞茬喖寮诲☉銏╂晝闁挎繂妫涢ˇ銊╂⒑缁嬪潡顎楃紒澶婄秺瀵鈽夐姀鐘插祮闂侀潧顭堥崕閬嶏綖椤忓牊鈷戦悹鍥ㄥ絻閻︺劑鏌涢悩宕囧⒌婵犫偓娓氣偓濮婅櫣绱掑鍡欏姺闂佺绨洪崐妤€鈽夐崹顐犲亝闁告劏鏅濋崢鍗烆渻閵堝骸骞楅柛銊ョ－閼鸿鲸绂掔€ｎ偆鍘?
        target_database: 闂傚倸鍊搁崐鐑芥嚄閸洖纾块柣銏㈩焾閻ょ偓绻濋棃娑卞剰闁搞劌鍊搁埞鎴﹀磼濮橆厼鏆堥梺缁樻尰缁嬫垿婀侀梺鎸庣箓閹冲繘骞嗛崼鐔翠簻闁挎繂鐗嗘禍褰掓煃瑜滈崜婵嬶綖婢舵劕绠伴柣鎴ｅГ閸婂潡鏌ㄩ弴鐐测偓鍝ョ不濮樿埖鐓涢柛鎰╁妿婢ф洜绱掗悩宸吋闁哄睙鍡欑杸闁挎繂鎳嶇花濠氭⒑闁偛鑻晶顔剧棯缂併垹骞樻俊鍙夊姍楠炴帡骞樺畷鍥╃嵁濠电姷鏁告慨鎾磹婵犳碍鍎庨幖杈剧悼绾捐棄霉閿濆嫮鐭欓柛婵囨そ閺岋綁鎮㈤崣澶嬬彅闂佷紮绲块崗姗€寮幇顓炵窞濠电姴瀚慨锔戒繆閻愵亜鈧牕顔忔繝姘；闁圭偓鐣禍婊呮喐婢舵劕纾婚柟鎯у绾捐棄霉閿濆嫮鐭欓柛婵婃閳ь剙鍘滈崑鎾绘煙闂傚顦﹂柡瀣╄兌閳ь剙绠嶉崕鍗灻洪敐鍛煢妞ゅ繐濞婅ぐ鎺撳亹鐎瑰壊鍠栭崜浼存⒑閸涘﹤鐏╁┑顔炬暩閹广垹鈹戦崶鈺冪槇闂佺鏈崙瑙勭婵傚憡鈷戝ù鍏肩懅閻ｈ京绱撳鍜冭含妤犵偛鍟灃闁告劏鏅涢弸鍌炴⒑閸涘﹥澶勯柛鐘崇墵钘熸繝闈涱儐閳锋垿鏌涢幘鐟扮毢闁告ɑ鐩弻娑㈠Ω閵壯冪厽闂佺粯渚楅崰鏍敇閸忕厧绶炲┑鐘插婵附淇婇悙顏勨偓鏍暜閹烘柡鍋撳鐓庡闁逞屽墯閼归箖藝椤栫偐鈧妇鎹勯妸锕€纾繛鎾村嚬閸ㄤ即宕滈柆宥嗏拺閻犲洦褰冮惁銊╂煕閻樺磭澧垫繝鈧笟鈧铏圭磼濮楀棛鍔搁柣蹇撶箲閻熲晛鐣峰ú顏呮櫜濠㈣泛顑囬崢閬嶆椤愩垺澶勬俊顐ｅ灴閹虫挾鎹勯妸銏犱壕閻熸瑥瀚粈鍐┿亜閵娿儳澧﹂柛鈹惧亾濡炪倖宸婚崑鎾寸節閳ь剚娼忛妸锕€寮块悗瑙勬礀濞层倝宕瑰┑瀣厵闁告挆鍛闂佺粯鎸诲ú鐔煎蓟閻斿吋鍊绘俊顖濆吹閸欏棗顪冮妶蹇曞埌闁靛牏顭堥～蹇涙倻濡顫￠梺鐟板槻閼活垶宕㈤埄鍐瘈闁冲皝鍋撻柛鏇炵仛閻ｅ爼姊烘导娆戝埌闁诲繑宀搁獮蹇涘川椤栨稑鏋傞梺鍛婃处閸嬪嫭淇?

    Returns:
        闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁撻悩鍐蹭罕闂佸搫娲㈤崹鍦不閻樿绠规繛锝庡墮婵¤偐绱掗悩鍐插摵闁哄本鐩、鏇㈠Χ閸涱喚浜栭梻浣哥－缁垶寮婚妸鈺佺厴闁硅揪闄勯崑鎰板级閸偄浜滈柛姗堢節濮婅櫣绱掑Ο鍝勵潓闂佹寧娲╂俊鍥ｉ幇鏉跨閻庢稒锚椤庢捇鏌ｉ悢鍝ユ噧閻庢凹鍓熷Λ鍕吋婢跺鎷洪柣鐘叉穿鐏忔瑧绮婚悧鍫涗簻闁挎梻鍋撻弳顒侇殽閻愬弶顥㈢€规洘锕㈤、娆撴嚃閳哄﹥效濠碉紕鍋戦崐鏍礉閹达箑纾归柡宥庡幖缁犵喎鈹戦悩宕囶暡闁?
    """
    print(f"\n{'='*50}")
    print("Log message")
    if target_database:
        print("Log message")
    print(f"{'='*50}")

    # 濠电姷鏁告慨鐑姐€傞挊澹╋綁宕ㄩ弶鎴狅紱闂侀€炲苯澧撮柡灞剧〒閳ь剨缍嗛崑鍛暦瀹€鍕厸鐎光偓鐎ｎ剛锛熸繛瀵稿婵″洭骞忛悩璇茬闁圭儤鍩堝銉モ攽閻樻鏆柍褜鍓欓崯璺ㄧ棯瑜旈弻鐔碱敊閻撳簶鍋撻幖浣瑰仼闁绘垼妫勫敮闂佸啿鎼崐鐟扳枍閸℃稒鈷戦柛蹇涙？閼割亪鏌涙惔銏犫枙闁诡噣绠栭獮搴ㄦ嚍閵夈垺瀚奸梻浣告啞缁诲倻鈧凹鍓熼崺鈧い鎺戝亞閻掗箖鎮￠妶澶嬬叆婵犻潧妫欓崳鎶芥煛?
    if not files or len(files) == 0:
        print("Log message")
        raise HTTPException(status_code=400, detail="Request failed")

    results = []

    for i, file in enumerate(files):
        try:
            print("Log message")
            print("Log message")
            print("Log message")

            # 濠电姷鏁告慨鐑姐€傞挊澹╋綁宕ㄩ弶鎴狅紱闂侀€炲苯澧撮柡灞剧〒閳ь剨缍嗛崑鍛暦瀹€鍕厸鐎光偓鐎ｎ剛锛熸繛瀵稿婵″洭骞忛悩璇茬闁圭儤鍩堝銉╂⒒閸屾瑧顦﹂柟纰卞亰椤㈡牠宕ㄩ弶鎴犳焾濡炪倖鐗楃划搴ㄦ儗婢舵劖鐓欓柣鎴炆戦埛鎰偓瑙勬礀椤︾敻寮婚悢纰辨晣闁绘棃顥撻悷鎰攽閻愬樊鍤熼柛蹇旓耿瀵?
            if hasattr(file, 'size') and file.size and file.size > 50 * 1024 * 1024:  # 50MB
                raise ValueError("Invalid request")

            # 闂傚倸鍊峰ù鍥х暦閸偅鍙忛柡澶嬪殮濞差亜鐓涢柛婊€鐒﹂弲顏堟偡濠婂嫬鐏村┑锛勬暬楠炲洭寮剁捄銊モ偓鐐差渻閵堝棗鍧婇柛瀣尰娣囧﹪顢曢敐蹇氣偓鍧楁煛鐏炲墽娲村┑锛勫厴椤㈡盯鎮欓幖顓涘亾瀹ュ拋娓婚柕鍫濇婵啰绱掗鐣屾噰鐎殿喛顕ч埥澶愬閻樼數鏉告俊鐐€栫敮濠勭矆娴ｇ硶鏋?
            print("Log message")
            content = await file.read()
            print("Log message")

            if len(content) == 0:
                raise ValueError("Invalid request")

            # 婵犵數濮烽弫鎼佸磿閹寸姴绶ら柦妯侯棦濞差亝鏅滈柣鎰靛墮鎼村﹪姊虹粙璺ㄧ伇闁稿鍋ゅ畷鎴﹀Χ婢跺鍘繝鐢靛仧閸嬫挸鈻嶉崨顔荤箚妞ゆ劧缍囬懓鍧楁煛鐏炲墽娲村┑锛勫厴椤㈡盯鎮欓幖顓涘亾瀹ュ拋娓?- 婵犵數濮烽弫鎼佸磻閻斿澶愬箛閺夎法锛涢梺褰掑亰閸樹粙宕ｈ箛娑欑厵缂備降鍨归弸娑㈡煟椤撶噥娈滈柡灞剧洴閸╁嫰宕橀浣割潓闂備胶顭堟鎼佹煀閿濆钃熼柨婵嗩槸閸愨偓闂佹眹鍨婚弫姝屸叺闂佽瀛╅鏍闯椤曗偓瀹曟垶绻濋崶褏鐣洪悷婊勬煥閻ｇ兘鎮℃惔妯绘杸闂佸壊鍋呯粙鎴炵娴煎瓨鈷?
            print("Log message")

            # 婵犵數濮烽弫鍛婃叏閻戝鈧倹绂掔€ｎ亞鍔﹀銈嗗坊閸嬫捇鏌涢悢閿嬪仴闁糕斁鍋撳銈嗗坊閸嬫挾绱撳鍜冭含妤犵偛鍟灒閻犲洩灏欑粣鐐烘⒑瑜版帒浜伴柛鎾寸洴椤㈡瑩宕堕浣叉嫼闂佺鍋愰崑娑㈠礉閳ь剟姊洪崨濠佺繁闁哥姵顨婇幆渚€鎮欏ù瀣杸闂佺粯鍔樼亸娆撳箺閻樼數纾兼い鏃囧亹閻掑摜鈧鍠撻崝鎴﹀箚閸岀偞鍎岄柣鐐甸ケme闂傚倸鍊搁崐鐑芥倿閿旈敮鍋撶粭娑樻噽閻瑩鏌熺€电浠ч梻鍕閺岋繝宕橀敐鍛缂傚倷鑳剁划顖炴儎椤栨氨鏆﹂柛顐ｆ处閺佸棗霉閿濆娅滅紓鍌涙崌濮婄粯鎷呴悷鏉款潽闂佺顑呴幊妯讳繆閸洖围濠㈣泛顑傞幏鍝勨攽椤旂偓鍤€婵炲眰鍊栨穱濠冪附閸涘﹤鈧灚鎱ㄥΟ鐓庡付鐎殿噮鍠氶埀顒侇問閸犳绻涙繝鍥х畺闁靛繈鍊栭崑鍌炲箹鏉堝墽绉甸柛鐐叉贡缁辨捇宕掑▎鎾搭€栭梺鍛婃⒐閸ㄥ墎绮嬪鍥ㄥ磯闁惧繗顫夊▓?
            effective_target_db = target_database
            if kb_name:
                kb = await kb_manager.get_kb(kb_name, owner_user_id=user.get("id"), include_legacy=True)
                if kb:
                    effective_target_db = kb["database_name"]
                else:
                    raise ValueError("Invalid request")
            elif effective_target_db:
                effective_target_db = namespace_database_name(effective_target_db, user)
            else:
                effective_target_db = namespace_database_name(Path(file.filename).stem, user)

            file_info = await file_manager.save_uploaded_file(
                content,
                file.filename,
                target_database=effective_target_db,
                owner_user_id=user.get("id"),
            )

            # 闂傚倸鍊搁崐鐑芥嚄閸洍鈧箓宕奸姀鈥冲簥闂佽澹嗘晶妤呭磻椤忓牊鐓曢柕澶涚到婵℃寧銇勯埡鍐ㄥ幋闁哄本鐩、鏇㈡偐閹绘帒顫氶梻浣侯焾鐎涒晠銆冩繝鍥ц摕闁哄洨鍠庣欢鐐烘煕椤愶絿绠撴い顒€顑呴埞鎴﹀灳閸愯尙楠囧┑鐐跺皺閸犳牠鎮?
            if kb_name:
                file_manager.update_file_kb(file_info["file_id"], kb_name)

            file_info["status"] = "uploaded"
            file_info["size"] = len(content)
            print("Log message")
            print("Log message")
            print("Log message")
            print("Log message")

            results.append(file_info)

        except Exception as e:
            error_msg = "Operation failed"
            print(f"[ERROR] {error_msg}")
            main_logger.error(error_msg)
            results.append({
                "filename": getattr(file, "filename", "unknown"),
                "status": "error",
                "error": safe_str(e)
            })

    print("Log message")
    print(f"{'='*50}")

    return {"files": results}

@app.delete("/files/{file_id}")
async def delete_file(file_id: str, clean_database: bool = False, user: dict = Depends(require_current_user)):
    file_info_for_auth = file_manager.get_file_by_id(file_id, owner_user_id=user.get("id"), include_legacy=True)
    if not file_info_for_auth:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    """
    闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁嶉崟顒佹闂佺粯鍔曢顓犵不妤ｅ啯鐓冪憸婊堝礈濮樿鲸宕叉繛鎴欏灩瀹告繃銇勯幘鍗炵仼鐎殿喗婢樿灃闁绘﹢娼ф禒锕傛煕閺冣偓閻熴儵鎮鹃悜钘夌畾闂侇叏闄勯瀷闂傚倷绀侀幖顐⑽涢弮鍫濈闁规儼妫勯拑鐔兼煥濠靛棭妲搁幆鐔兼⒑闂堟侗妲堕柛搴ｅ劋缁傛帗銈ｉ崘鈹炬嫼闂佸憡绻傜€氱兘宕曡箛娑欑厱闁绘洑绀侀悘锝囩磼?

    Args:
        file_id: 闂傚倸鍊搁崐椋庣矆娓氣偓楠炴牠顢曢敃鈧壕鍦磼鐎ｎ偓绱╂繛宸簼閺呮煡鏌涘☉鍙樼凹闁诲氦顕ч—鍐Χ閸愩劎浼勯梺?
        clean_database: 闂傚倸鍊搁崐椋庣矆娓氣偓楠炴牠顢曢妶鍌氫壕婵鍘у顔锯偓瑙勬礃濞叉鎹㈠┑瀣倞闁靛ě鍐ㄧ疄濠电姵顔栭崰妤呮晝閳哄懎绀堟慨姗嗗墾閼板潡鏌ｅΔ鈧悧鍛崲閸℃稒鐓熼柟閭﹀幖缁插鏌嶈閸撴岸骞冮崒娑楃箚闁圭虎鍠栫粻铏繆閵堝倸浜鹃悗鐟版啞缁诲啴濡甸崟顖氬唨闁靛ě鈧Σ鍫ユ⒑闁偛鑻晶浼存煕鐎ｃ劌鈧繂顕ｆ繝姘労闁告劏鏅涢鎾绘⒑閸涘﹦绠撻悗姘卞厴瀵娊顢橀姀鈥斥偓鐢告偡濞嗗繐顏悘蹇ｅ亰閺岋綁骞掗悙鐢垫殼濡ょ姷鍋涘Λ婵嗩嚕椤曗偓瀹曠厧鈹戦崼顐㈡櫔闂傚倷娴囨竟鍫熺珶閸績鏋栨繛鎴欏灮瀹撲線鏌嶈閸撶喎顫忕紒妯诲闁革富鍘介懣鍥⒑閸涘﹥鐓ラ柣顒€銈搁崺鈧い鎺嶇閸ゎ剟鏌涢幘瀵搞€掗柛鎺撳笚缁绘繈宕堕妸銉ょ紦缂傚倷绀侀鍫濃枖閺団懞鍥樄婵﹥妞藉Λ鍐ㄢ槈鏉堫煈鈧棝姊婚崒姘仼閻庢凹鍓熼崺銏ゅ箻鐠囨煡鍞堕梺鍝勬川閸犳捇宕?
    """
    try:
        # 闂傚倸鍊搁崐椋庣矆娓氣偓瀹曘儳鈧綆鍠栫壕鍧楁煙閹増顥夐幖鏉戯躬閺屻倝鎳濋幍顔肩墯婵炲瓨绮岀紞濠囧蓟濞戙垹唯妞ゆ棁宕甸弳妤佺箾鐎涙鐭婄紓宥咃躬瀵鎮㈤悡搴ｇ暰閻熸粌绉瑰铏綇閵婏絼绨婚梺闈涚墕閹冲繘宕抽搹鍦＜缂備焦顭囧ú鎾煙瀹曞洤校闁挎稒鍔曢埞鎴﹀幢濮楀棗鏁冲┑鐘垫暩婵敻顢欓弽顓炵獥闁圭儤顨呴悿楣冩煟濡鍤欑紒鐘冲哺閺屾盯骞囬棃娑欑亪缂備讲鍋撻柛鏇ㄥ厵娴滄粎鎲歌箛娑樻妞ゎ亞骞嶳AG闂傚倸鍊峰ù鍥敋瑜庨〃銉х矙閸柭も偓鍧楁⒑椤掆偓缁夊澹曠紒妯圭箚妞ゆ牗鑹鹃幃鎴炪亜閹邦亞鐭欓柡灞炬礃瀵板嫰宕卞Ο鑽ゅ絾闂備胶顭堥鍐礉閹达箑钃熼柡鍥╁枔缁犻箖鏌涢…鎴濇灀闁稿鎸歌灃闁告侗鍠栧▓鐐烘⒑缂佹ê濮﹂柛鎾寸〒缁粯銈ｉ崘鈺冨幍闂佺顫夐崝鏍偟椤忓牊鐓曢柨婵嗗閻瑩鏌″畝鈧崰鏍€佸▎鎴炲厹闁汇値鍨伴幆鍫ユ煟鎼淬埄鍟忛柛锝庡櫍瀹曟垶绻濋崶褏鐣洪悷婊勬煥閻ｇ兘鎮℃惔妯绘杸闂佸壊鍋呯粙鎴炵娴煎瓨鈷?
        rag_instance = None
        if clean_database:
            # 闂傚倸鍊搁崐椋庣矆娓氣偓瀹曘儳鈧綆鍠栫壕鍧楁煙閹増顥夐幖鏉戯躬閺屻倝鎳濋幍顔肩墯婵炲瓨绮岀紞濠囧蓟濞戙垹唯妞ゆ梹鍎崇敮銉モ攽閻愬瓨宕勯柛鈺傜墬缁岃鲸绻濋崶鑸垫櫖濠殿喗锕╅崢鍏肩閹绢喗鍊垫繛鍫濈仢濞呮﹢鏌涚€ｎ亷韬鐐插暢椤﹀湱鈧娲滈崢褔鍩為幋锕€閱囨繛鎴灻奸崰濠囨⒒閸屾瑧顦︽繝鈧柆宥呭偍鐟滄棃骞冨ú顏勎╅柍杞拌兌椤斿洭姊虹拠鈥崇€婚柍褜鍓熷鎼佸籍閸喓鍘甸柡澶婄墑閸斿秹寮查悹绔恟RAG闂傚倸鍊峰ù鍥敋瑜庨〃銉х矙閸柭も偓鍧楁⒑椤掆偓缁夊澹曠紒妯圭箚妞ゆ牗鑹鹃幃鎴炪亜?
            try:
                rag_instance = get_or_create_hyperrag()
                main_logger.info("Log message")
            except Exception as e:
                main_logger.warning("Log message")
                clean_database = False

        success = file_manager.delete_file(file_id, clean_database=clean_database, rag_instance=rag_instance)

        if success:
            message = "Operation failed"
            if clean_database and rag_instance:
                message += " Additional details available in logs."
            return {"success": True, "message": message}
        else:
            raise HTTPException(status_code=404, detail="Knowledge base not found")
    except Exception as e:
        main_logger.error("Log message")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/database/clear")
async def clear_database(database: str = "default", user: dict = Depends(require_current_user)):
    database = require_database_access(database, user) or namespace_database_name("default", user)
    """
    濠电姷鏁告慨鐑藉极閹间礁纾婚柣鎰惈缁犱即鏌熼梻瀵割槮缂佺姷濞€閺岀喖鎮ч崼鐔哄嚒闂佺粯鎸婚敃銏ゅ蓟閳ユ剚鍚嬮幖绮光偓宕囶啇缂傚倷鑳舵慨鎶藉础閹惰棄钃熸繛鎴欏灩鍞梺鐟扮摠缁诲啴宕抽悜妯诲弿闁挎繂鎳橀崣鍕叏婵犲嫬鍔嬫繛纰变邯楠炲繒浠﹂挊澶婅厫婵犵數濮幏鍐礋閸偆鏆ラ梻浣风串缁蹭粙鎮樺璺虹闁告侗鍨遍崰鍡涙煕閺囥劌浜滃┑鈩冨▕濮婄粯鎷呯粵瀣秷閻庤娲橀敃銏犵暦濞差亜鍐€妞ゆ挾鍠庢禒濂告⒒娓氬洤澧紒澶屾暬閹€斥枎閹寸姵锛忛梺缁橆殔閻擃偊顢旈崨顖ｆ锤婵°倧绲介崯顖炲煕閹达附鐓曟繝闈涙椤忣偄顭胯濞叉﹢濡甸崟顖涙櫆闁割煈鍠栫粊顕€鎮楀▓鍨灍濠电偛锕獮鍐閵堝棗浜楅柟鑹版彧缂嶅棝宕?

    Args:
        database: 闂傚倸鍊搁崐宄懊归崶褜娴栭柕濞炬櫆閸ゅ嫰鏌ょ粙璺ㄤ粵婵炲懐濮垫穱濠囧Χ閸屾矮澹曢梻浣风串缁蹭粙鎮樺璺虹闁告侗鍨遍崰鍡涙煕閺囥劌浜滃┑鈩冨▕濮婄粯鎷呯粵瀣秷閻庤娲橀敋闁宠绉瑰鎾閻樼绱柣搴ゎ潐濞叉牕煤閵娧冾棜?
    """
    try:
        main_logger.info("Log message")

        # 濠电姷鏁告慨鐑藉极閹间礁纾婚柣鎰惈缁犱即鏌熼梻瀵割槮缂佺姷濞€閺岀喖鎮ч崼鐔哄嚒闂佺粯鎸婚敃銏ゅ蓟閿熺姴閱囬柣鏃€鍝洪埡鐞玶RAG闂傚倸鍊峰ù鍥敋瑜庨〃銉х矙閸柭も偓鍧楁⒑椤掆偓缁夊澹曠紒妯圭箚妞ゆ牗鑹鹃幃鎴炪亜閹邦亞鐭欓柡灞炬礃缁旂喖顢涘顓炴闂佹寧绋掔换鍫濐潖閾忚鍠嗛柛鏇ㄥ亜婵垻绱掗崜褑妾搁柛娆忓暣閻?
        if database in hyperrag_instances:
            del hyperrag_instances[database]
            main_logger.info("Log message")

        # 闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁嶉崟顒佹闂佺粯鍔曢顓犵不妤ｅ啯鐓冪憸婊堝礈濮樿鲸宕叉繛鎴欏灩瀹告繃銇勯幘鍗炵仼鐎殿喕鍗抽幃妤€鈻撻崹顔界彯闂佺顑呴敃顏堢嵁閸愵収妯勯悗瑙勬礈閸樠囧煘閹达箑閱囨繛鎴灻奸崰濠囨⒒閸屾瑧顦︽繝鈧柆宥呭偍鐟滄棃骞冨ú顏勎╅柍杞拌兌椤斿洦绻濋悽闈浶ｉ柤褰掔畺瀹曟瑩鎮╃紒妯煎幈闂佺鍩囬崝宥呪枍閸ャ劊浜滈柍鍝勫暙閸樻挳鏌熼娆炬綈闁瑰嘲鎳樺畷銊︾節閸涱垼鏀ㄧ紓鍌氬€风拋鏌ュ磻閹剧粯鐓曢柡鍥ュ妼閳ь剚鎸婚幆鏃堝Ω閵壯冣偓鐐烘⒑闂堟丹娑㈠川椤栨稒鐦旈梻鍌氬€风粈渚€骞栭鈶芥稑鐣濋崟顐わ紱闂佺懓澧界划顖炲煕閹达附鐓曟繝闈涙椤忊晠鏌￠崱妯活棃闁哄本绋掗幆鏃堝Χ閸曨偅鍎撻梻浣烘嚀缁犲秹宕归挊澶樺殨妞ゆ洍鍋撶€规洜鍘ч埞鎴﹀炊閼告妫ㄩ梻鍌氬€烽悞锕傚箖閸洖纾垮┑鐘崇閳锋棃鏌涢弴銊ョ伇闁轰礁鍟湁闁绘ê妯婇崕鎰版煟閹惧崬鍔滅紒缁樼洴楠炲鎮滈崱娆忓Ш闂備胶绮敮鐐衡€﹂崼銉︾畳闂佽绻愮换鎴︽偋濡も偓閳诲秵绻濋崟銊ヤ壕閻熸瑥瀚粈鍐┿亜閵娿儲鍤囨い銏∩戠缓鐣岀矙閸喛鈧灝鈹戦埥鍡楃仩闁汇劎鍏樺畷鎴﹀箻濞茬粯鏅╁┑鐐存綑妤犲摜绱炴繝鍥х畺闁冲搫鎳忛崐缁樹繆椤栨粠鍎犻柍褜鍓氶崝娆撳箖濡ゅ啯鍠嗛柛鏇ㄥ墰閿涙盯姊洪崨濠庢畷濠电偛锕悰顕€宕橀埡鍐炬祫闁诲函缍嗛埀顒夊幐閺呯娀寮诲澶婁紶闁告洦鍋€閸嬫捇鎮烽幍铏€洪梺鐟板⒔缁垶鎮￠悢鍏肩厽婵☆垰鎼痪褏鈧懓鎲＄换鍕閹烘鐒?
        db_path = Path(hyperrag_working_dir) / database
        if db_path.exists():
            import shutil
            # 婵犵數濮烽弫鎼佸磿閹寸姴绶ら柦妯侯棦濞差亝鏅滈柣鎰靛墮鎼村﹪姊洪崨濠冨闁搞劍婢樻晥闁哄被鍎查悡鍐喐濠婂牆绀堥柣鏃傚帶閽冪喖鏌ㄩ悢鍝勑㈢紒鈧崘顔界叆闁哄洦顨呮禍楣冩⒑閸涘﹥鈷愭慨妯稿妿濡叉劙骞掗弮鍌滐紲濠碘槅鍨卞鍨涢崘顔藉€垫繛鍫濈仢濞呮﹢鏌涢幘璺烘瀻闁伙絿鍏樺畷濂稿即閻斿憡鐝曠紓鍌欑劍缁嬫垿顢栭崨顔绢浄婵炲樊浜濋埛鎺懨归敐鍥ㄥ殌妞ゆ洘绮庣槐鎺斺偓锝庡亜閻忔挳鏌熷畷鍥ф灈妞ゃ垺绋戦埞鎴﹀礋椤忓懐娼栭梺鑽ゅ枑缁秹寮婚妸鈺傚仼鐎瑰嫰鍋婂鈺呮煠閹间焦娑уù婊冩贡缁辨捇宕掑▎鎴濆濡炪値鍘煎ú鈺呭Φ閹版澘绠ｉ柨鏃囆掗幏娲煛婢跺苯浠﹀┑顖欑矙瀹曟浠︾粵瀣數閻熸粌閰ｉ妴鍐川鐎涙ê浠奸梺鍓茬厛閸嬪棝鎮疯ぐ鎺撶厓鐟滄粓宕滃▎鎿冩晪闁挎繂顦介弫鍡涙煕閺囥劌浜為柛濠勫仱濮婃椽骞愭惔鈶╂嫽闂佺儵鍓濆Λ鍐ㄧ暦?
            data_files_to_delete = []
            for item in db_path.iterdir():
                if item.is_file() and not item.name.endswith('.log'):
                    data_files_to_delete.append(item)
                elif item.is_dir():
                    # 闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁嶉崟顒佹闂佺粯鍔曢顓犵不妤ｅ啯鐓冪憸婊堝礈濮樿鲸宕叉繛鎴欏灩瀹告繃銇勯幘璺烘瀾鐎规洘濞婂娲焻閻愯尪瀚板褜鍨崇槐鎺斺偓锝庡亜濞搭喚鈧娲樼换鍌濈亙闂侀€炲苯澧伴柛娆忔嚇濮婃椽鎮烽弶鎸幮╅柣鐐村嚬閸嬪懐绮嬪鍫涗汗闁圭儤鎸鹃崢鎼佹⒑閹肩偛鍔橀柛鏂款儐缁傚秹濮€閵堝棛鍘卞┑顔筋殔濡鏅堕幘顔界厸鐎光偓鐎ｎ剛袦婵犵鍓濋幃鍌涗繆閻戣棄唯妞ゆ棁宕靛Λ顖涚節閻㈤潧袥闁瑰嘲鍟村畷姗€顢撻鍡楁噳閸嬫挸鈻撻崹顔界亪闂佽绻戦懝楣冾敋閵夆晛绀嬫い鎾寸☉娴滈箖鏌ㄥ┑鍡涱€楀ù婊呭仱閺屽秷顧侀柛鎿勭畵瀹曚即寮介鐔虹暢闂傚倷鑳剁划顖滄箒闁荤姭鍋撻柨鏇炲€搁悿顕€鏌涢妷銏℃珖缁炬儳銈稿鍫曞醇濞戞ê顬嬮梺鐟板暱濞诧箓骞堥妸锔剧瘈濞达綀娅ｉ悡鎾寸節绾版ǚ鍋撳畷鍥х厽閻庤娲滈崰鏍€佸鈧幃娆戔偓娑欘焽瑜?log闂傚倸鍊搁崐椋庣矆娓氣偓楠炴牠顢曢敃鈧壕鍦磼鐎ｎ偓绱╂繛宸簼閺呮煡鏌涘☉鍙樼凹闁诲骸顭峰娲濞戞氨鐤勯梺绋匡攻閻楃姴顕?
                    for sub_item in item.rglob('*'):
                        if sub_item.is_file() and not sub_item.name.endswith('.log'):
                            try:
                                sub_item.unlink()
                            except Exception as e:
                                main_logger.warning("Log message")

            # 闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁嶉崟顒佹闂佺粯鍔曢顓犵不妤ｅ啯鐓冪憸婊堝礈濮樿鲸宕叉繛鎴欏灩瀹告繃銇勯幘鍗炵仼鐎殿喕鍗抽幃妤€鈻撻崹顔界彯闂佺顑呴敃顏堢嵁閸愵収妯勯悗瑙勬礈閸樠囧煘閹达箑閱囨繛鎴灻奸崰濠囨⒒閸屾艾鈧绮堟笟鈧獮鏍敃閿曗偓绾惧湱绱掔€ｎ偓绱╂繛宸簼閺呮煡鏌涘☉鍙樼凹闁?
            for file in data_files_to_delete:
                try:
                    file.unlink()
                    main_logger.info("Log message")
                except Exception as e:
                    main_logger.warning("Log message")

            # 闂傚倸鍊峰ù鍥敋瑜忛幑銏ゅ箛椤旇棄搴婇梺鐟邦嚟婵潧鐣烽弻銉︾厱闁斥晛鍟伴埊鏇㈡煕鎼粹槄鏀婚柕鍥у瀵粙顢曢～顓犳崟缂傚倷璁查崑鎾绘煕閳╁啰鈯曢柣鎾跺枑娣囧﹪顢涘┑鍡曟睏闁汇埄鍨遍惄顖炲蓟閿濆應鏀介柛顐ｇ箖閻忎胶绱撴担浠嬪摵閻㈩垱甯￠幃鎯р攽鐎ｎ亞顦ㄩ梺鍐叉惈閿曪綁宕Δ浣虹瘈闁汇垽娼ф禒婊呪偓娈垮枦閸╂牠宕氭繝鍐浄閻庯綆鈧?
            for item in db_path.iterdir():
                if item.is_dir():
                    try:
                        shutil.rmtree(item)
                    except Exception as e:
                        main_logger.warning("Log message")

            main_logger.info("Log message")

        return {
            "success": True,
            "message": "Operation completed",
            "database": database
        }
    except Exception as e:
        main_logger.error("Log message")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/database/status")
async def get_database_status(database: str = "default", user: dict = Depends(require_current_user)):
    database = require_database_access(database, user) or namespace_database_name("default", user)
    """
    闂傚倸鍊搁崐椋庣矆娓氣偓瀹曘儳鈧綆鍠栫壕鍧楁煙閹増顥夐幖鏉戯躬閺屻倝鎳濋幍顔肩墯婵炲瓨绮岀紞濠囧蓟濞戙垹唯妞ゆ梻鍘ч～鈺呮⒑閸濆嫷鍎庣紒鑸靛哺瀵鏁愰崨鍌涙閸┾偓妞ゆ帒瀚崑瀣煕閳╁啰鎳呴柣顓炵墦閺屻劑寮撮悙娴嬪亾閸濄儳涓嶇憸鐗堝笚閸婂灚绻涢幋鐑嗕紗闁瑰濮抽悞濠囨⒒閸喓鈻撻柡鈧懞銉ｄ簻闁哄啫娲よ闂佺锕ラ崝鏍€冮妷鈺傚€烽柍杞版婢规洘绻濋悽闈涗哗闁规椿浜炵槐鐐哄焵椤掍胶绠鹃柟鎹愭珪鐠愶繝鏌熼獮鍨伈鐎规洖宕埥澶娾枎閹存繂绠?

    Args:
        database: 闂傚倸鍊搁崐宄懊归崶褜娴栭柕濞炬櫆閸ゅ嫰鏌ょ粙璺ㄤ粵婵炲懐濮垫穱濠囧Χ閸屾矮澹曢梻浣风串缁蹭粙鎮樺璺虹闁告侗鍨遍崰鍡涙煕閺囥劌浜滃┑鈩冨▕濮婄粯鎷呯粵瀣秷閻庤娲橀敋闁宠绉瑰鎾閻樼绱柣搴ゎ潐濞叉牕煤閵娧冾棜?
    """
    try:
        # 濠电姷鏁告慨鐑姐€傞挊澹╋綁宕ㄩ弶鎴狅紱闂侀€炲苯澧撮柡灞剧〒閳ь剨缍嗛崑鍛暦瀹€鍕厸鐎光偓鐎ｎ剛锛熸繛瀵稿婵″洭骞忛悩璇茬闁圭儤鍩堝銉╂⒒閸屾瑧顦﹂柟纰卞亜铻炴繛鎴欏灩缁愭鏌″搴″箻鐎规挷绶氶弻鐔衡偓鐢殿焾闉嬫繝娈垮枟婵炲﹤顫忓ú顏嶆晢闁逞屽墰缁棃骞橀鑲╃厬婵犵數濮村ú锕傛偂濞嗘劑浜滈柡宥冨妿閹冲棝鏌涜箛鎾剁劯闁哄苯绉烽¨渚€鏌涢幘瀛樼殤缂侇喗鐟╅獮鎺懳旀担瑙勭彣婵犵數濮烽弫鍛婃叏椤撱垹纾?
        db_path = Path(hyperrag_working_dir) / database
        db_exists = db_path.exists()

        # 闂傚倸鍊搁崐椋庣矆娓氣偓瀹曘儳鈧綆鍠栫壕鍧楁煙閹増顥夐幖鏉戯躬閺屻倝鎳濋幍顔肩墯婵炲瓨绮岀紞濠囧蓟濞戙垹唯妞ゆ梻鍘ч～鈺呮⒑閸濆嫷鍎庣紒鑸靛哺瀵鏁愰崨鍌涙閸┾偓妞ゆ帒瀚崑瀣煕閳╁啰鎳呴柣顓炵墦閺屻劑寮撮悙娴嬪亾閸濄儳涓嶇憸鐗堝笚閸婂灚绻涢幋鐑嗕紗闁瑰濮抽悞濠冦亜閹惧崬鐏柣鎾崇箻閺屾盯濡烽幋婵嗩仼缂佹劖绋掔换?
        db_size = 0
        if db_exists:
            for file_path in db_path.rglob("*"):
                if file_path.is_file():
                    db_size += file_path.stat().st_size

        # 闂傚倸鍊搁崐椋庣矆娓氣偓瀹曘儳鈧綆鍠栫壕鍧楁煙閹増顥夐幖鏉戯躬閺屻倝鎳濋幍顔肩墯婵炲瓨绮岀紞濠囧蓟濞戙垹唯闁靛繆鍓濆鎺楁⒑缁嬫鍎愰柟鐟版搐閻ｇ兘鎮滅粵瀣櫍闂佺粯鍔栨竟鍡涙煢閻㈢數纾介柛灞剧懄缁佹壆绱撻崼婊冨祮鐎规洘娲熼幃鐣岀矙鐠恒劎鏆梻浣稿暱閹碱偊骞婅箛娑樺惞閻庯綆鍓涘Λ顖炴煟濡も偓閻擃偊顢旈崨顖ｆ锤?
        has_instance = database in hyperrag_instances

        return {
            "database": database,
            "exists": db_exists,
            "has_instance": has_instance,
            "size_bytes": db_size,
            "size_mb": round(db_size / (1024 * 1024), 2),
            "path": str(db_path)
        }
    except Exception as e:
        main_logger.error("Log message")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/databases/{database_name}/diagnose")
async def diagnose_database(database_name: str, user: dict = Depends(require_current_user)):
    database_name = require_database_access(database_name, user)
    """
    闂傚倸鍊峰ù鍥х暦閸偅鍙忛柡澶嬪殮濞差亜围濠㈣泛顑嗗▍鍥⒑闂堟侗妲撮柡鍛洴閹锋垿鎮㈤崗鑲╁幈闂侀潧顦介崰鏍ㄦ櫠椤曗偓閺岋紕鈧絺鏅濈粣鏃堟煛瀹€瀣埌閾绘牠鏌嶈閸撶喖骞冭瀹曞崬鈻庨幋鐘靛姼闂備焦瀵уú鏍磹閸濄儳涓嶇憸鐗堝笚閸婂灚绻涢幋鐑嗕紗闁瑰濮抽悞濠偯归悡搴ｆ憼闁绘挻鐩幃妤呮晲鎼存繄鐩庨梺鍝勬閸嬬喓妲愰幒妤€纾兼繛鎴烆焽椤戝倿姊洪崷顓熷殌閻庢碍婢橀悾鐑筋敃閿曗偓缁€瀣亜閹捐泛孝闁绘劕锕濠氬磼濞嗘垵濡藉┑锛勫仜閻忔繈鈥﹂崶顒€閿ゆ俊銈傚亾缂佲偓婢跺备鍋撻獮鍨姎妞わ富鍨虫竟鏇㈠锤濡ゅ啫褰勯梺鎼炲劘閸斿酣鍩ユ径宀€纾奸柍?

    Args:
        database_name: 闂傚倸鍊搁崐宄懊归崶褜娴栭柕濞炬櫆閸ゅ嫰鏌ょ粙璺ㄤ粵婵炲懐濮垫穱濠囧Χ閸屾矮澹曢梻浣风串缁蹭粙鎮樺璺虹闁告侗鍨遍崰鍡涙煕閺囥劌浜滃┑鈩冨▕濮婄粯鎷呯粵瀣秷閻庤娲橀敋闁宠绉瑰鎾閻樼绱柣搴ゎ潐濞叉牕煤閵娧冾棜?

    Returns:
        闂傚倸鍊峰ù鍥х暦閸偅鍙忛柡澶嬪殮濞差亜围濠㈣泛顑嗗▍鍥⒑闂堟侗妲撮柡鍛洴閹锋垿鎮㈤崗鑲╁幈闂侀潧顧€缁茶姤淇婇崸妤佺厓闁荤喐澹嗘晥闂佸搫鑻粔褰掑春閳╁啯濯撮柛娑橈攻椤撹法绱?
    """
    try:
        import psutil
        import os

        diagnosis = {
            "database": database_name,
            "hyperrag": {"exists": False, "path": "", "files": [], "processes": []},
            "cograg": {"exists": False, "path": "", "files": [], "processes": []},
            "instances": {
                "hyperrag": database_name in hyperrag_instances,
                "cograg": database_name in cograg_instances,
                "db_manager_hyperrag": f"{database_name}_hyperrag" in db_manager.databases,
                "db_manager_cograg": f"{database_name}_cograg" in db_manager.databases,
                "theme_db": database_name in db_manager.theme_databases
            }
        }

        # 闂傚倸鍊峰ù鍥х暦閸偅鍙忛柡澶嬪殮濞差亜围濠㈣泛顑嗗▍鍥⒑闂堟侗妲撮柡鍛洴閹?HyperRAG 闂傚倸鍊搁崐宄懊归崶褜娴栭柕濞炬櫆閸ゅ嫰鏌ょ粙璺ㄤ粵婵炲懐濮垫穱濠囧Χ閸屾矮澹曢梻浣风串缁蹭粙鎮樺璺虹闁告侗鍨遍崰鍡涙煕閺囥劌浜滃┑?
        hyperrag_path = os.path.join(hyperrag_working_dir, database_name)
        if os.path.exists(hyperrag_path):
            diagnosis["hyperrag"]["exists"] = True
            diagnosis["hyperrag"]["path"] = hyperrag_path

            # 闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁嶉崟顒佹濠德板€曢幊宀勫焵椤掆偓閸熸潙鐣烽妸鈺佺骇闁瑰瓨绻冮崕顏呬繆閻愵亜鈧牠骞愰崼鏇炲瀭闁革富鍘炬稉宥夋煏婢跺棙娅嗛柣鎾冲暟閹茬顭ㄩ崼婵堫槶闂佺粯鏌ㄩ〃搴ㄥ吹閺囥垺鐓曟い顓熷灥娴滄粎绱掗崜浣镐槐闁诡喗顨婇弫鎰償閳ヨ尙鏁栭梻渚€鈧偛鑻晶濠氭煕閻樺磭澧垫繝鈧?
            for root, dirs, files in os.walk(hyperrag_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    file_info = {
                        "path": file_path,
                        "size": os.path.getsize(file_path),
                        "locked": False
                    }

                    # 闂傚倸鍊峰ù鍥敋瑜忛幑銏ゅ箛椤旇棄搴婇梺鐟邦嚟婵潧鐣烽弻銉︾厱闁斥晛鍟伴埊鏇㈡煕鎼粹槄鏀婚柕鍥у瀵粙鈥﹂幋婵囶啌婵犵數鍋為崹顖炲垂瑜版帗鍊块柛顭戝亖娴滄粓鏌熼崫鍕棞濞存粓绠栧濠氬炊瑜滃Ο鈧梺璇″枟椤ㄥ﹪寮幇顓熷劅闁炽儴灏欓崙褰掓⒒娴ｇ瓔鍤欓悗鍨浮瀹曚即寮介鐔虹暢闂傚倷鑳剁划顖炴晪闂佸湱鈷堥崑濠囧箖閿熺姴绠涙い鎾寸箘缁犳岸姊洪崨濠勬噧妞わ缚鍗冲畷鎰板箛椤旂懓浜鹃悷娆忓绾炬悂鏌涙惔锝嗘毈鐎殿噮鍋婂畷姗€鍩￠崘顏呭殞闂備線鈧偛鑻晶瀵糕偓娈垮枛椤攱淇婇幖浣规櫆闁芥ê顦介埀顒佹崌濮婃椽宕ㄦ繝鍕窗闂佺瀛╄ぐ鍐暰?
                    try:
                        # 闂傚倸鍊峰ù鍥敋瑜忛幑銏ゅ箛椤旇棄搴婇梺鐟邦嚟婵潧鐣烽弻銉︾厱闁斥晛鍟伴埊鏇㈡煕鎼粹槄鏀婚柕鍥у瀵粙濡歌閳ь剚甯楅妵鍕煛閸愩劌骞嬮梺鍝勬湰濞叉绮╅悢纰辨晬婵﹩鍓氶悘鎾寸箾鐎电鈻堢紒鐘崇墪椤繐煤椤忓嫬绐涙繝鐢靛Т鐎涒晠鎮鹃崗鑲╃瘈婵炲牆鐏濋弸娆戠磼閹绘帩鐓肩€规洦鍨堕、娑㈡倷閺夋垟鍋撻崹顐ょ闁割偅绻勬禒銏ゆ煛鐎ｎ偆銆掔紒杈ㄥ笧缁辨帒螣閾忛€涙闂備礁鎼幊搴ㄦ偉婵傜鏋侀柛鎰靛枛閻掑灚銇勯幒鎴濐伌闁轰礁顑夐弻銊モ攽閸♀晜笑闂佺粯甯掗悘姘跺Φ閸曨垰绠抽柟瀛樼箥娴犵厧鈹戦埥鍡椾簼闁挎洏鍨藉璇测槈閵忕姈銊︺亜閺嶎偄浠︽い搴＄Т椤?
                        with open(file_path, 'a') as f:
                            pass
                    except (IOError, PermissionError):
                        file_info["locked"] = True
                        # 闂傚倸鍊峰ù鍥敋瑜忛幑銏ゅ箛椤旇棄搴婇梺鐟邦嚟婵潧鐣烽弻銉︾厱闁斥晛鍟伴埊鏇㈡煕鎼粹槄鏀婚柕鍥у瀵粙顢曢～顓犳崟闂備浇妫勯崯浼村窗閺嶎厼钃熼柡鍥╁枎缁剁偞绻涢幋鐐寸殤闁哄棛濮撮—鍐Χ閸愩劌濮曠紓浣筋嚙閻楁挸顕ｇ拠娴嬫婵☆垱绮嶅Λ鍐ㄧ暦濮椻偓婵℃悂骞囬埡浣稿Е闂佸搫澶囬崜婵嬪箯閸涘瓨顥堟繛鎴炲笒娴滅偓绻濋棃娑欙紞闁搞倖娲橀妵鍕箳閹存繍浠奸梺缁樺姇閿曨亪寮婚妸鈺佺睄闁稿本绮嶉幉姗€姊虹粙娆惧剭闁告梹鍨甸～蹇涘传閸曟嚪鍥х倞鐟滃秹鈥栭崼銉︾厽閹兼番鍨归崵顒勬煕閵婏箑鈻曟鐐村灴婵偓闁绘ɑ鐗滈崰鏍箠閺嶎厼鐓涢柛鎰典簻楠?
                        try:
                            for proc in psutil.process_iter(['pid', 'name', 'open_files']):
                                try:
                                    for item in proc.info['open_files'] or []:
                                        if file_path.lower() in item.path.lower():
                                            diagnosis["hyperrag"]["processes"].append({
                                                "pid": proc.info['pid'],
                                                "name": proc.info['name'],
                                                "path": item.path
                                            })
                                except (psutil.NoSuchProcess, psutil.AccessDenied):
                                    continue
                        except Exception:
                            pass

                    diagnosis["hyperrag"]["files"].append(file_info)

        # 闂傚倸鍊峰ù鍥х暦閸偅鍙忛柡澶嬪殮濞差亜围濠㈣泛顑嗗▍鍥⒑闂堟侗妲撮柡鍛洴閹?Cog-RAG 闂傚倸鍊搁崐宄懊归崶褜娴栭柕濞炬櫆閸ゅ嫰鏌ょ粙璺ㄤ粵婵炲懐濮垫穱濠囧Χ閸屾矮澹曢梻浣风串缁蹭粙鎮樺璺虹闁告侗鍨遍崰鍡涙煕閺囥劌浜滃┑?
        cograg_path = os.path.join(cograg_working_dir, database_name)
        if os.path.exists(cograg_path):
            diagnosis["cograg"]["exists"] = True
            diagnosis["cograg"]["path"] = cograg_path

            # 闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁嶉崟顒佹濠德板€曢幊宀勫焵椤掆偓閸熸潙鐣烽妸鈺佺骇闁瑰瓨绻冮崕顏呬繆閻愵亜鈧牠骞愰崼鏇炲瀭闁革富鍘炬稉宥夋煏婢跺棙娅嗛柣鎾冲暟閹茬顭ㄩ崼婵堫槶闂佺粯鏌ㄩ〃搴ㄥ吹閺囥垺鐓曟い顓熷灥娴滄粎绱掗崜浣镐槐闁诡喗顨婇弫鎰償閳ヨ尙鏁栭梻渚€鈧偛鑻晶濠氭煕閻樺磭澧垫繝鈧?
            for root, dirs, files in os.walk(cograg_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    file_info = {
                        "path": file_path,
                        "size": os.path.getsize(file_path),
                        "locked": False
                    }

                    # 闂傚倸鍊峰ù鍥敋瑜忛幑銏ゅ箛椤旇棄搴婇梺鐟邦嚟婵潧鐣烽弻銉︾厱闁斥晛鍟伴埊鏇㈡煕鎼粹槄鏀婚柕鍥у瀵粙鈥﹂幋婵囶啌婵犵數鍋為崹顖炲垂瑜版帗鍊块柛顭戝亖娴滄粓鏌熼崫鍕棞濞存粓绠栧濠氬炊瑜滃Ο鈧梺璇″枟椤ㄥ﹪寮幇顓熷劅闁炽儴灏欓崙褰掓⒒娴ｇ瓔鍤欓悗鍨浮瀹曚即寮介鐔虹暢闂傚倷鑳剁划顖炴晪闂佸湱鈷堥崑濠囧箖閿熺姴绠涙い鎾寸箘缁犳岸姊洪崨濠勬噧妞わ缚鍗冲畷鎰板箛椤旂懓浜鹃悷娆忓绾炬悂鏌涙惔锝嗘毈鐎殿噮鍋婂畷姗€鍩￠崘顏呭殞闂備線鈧偛鑻晶瀵糕偓娈垮枛椤攱淇婇幖浣规櫆闁芥ê顦介埀顒佹崌濮婃椽宕ㄦ繝鍕窗闂佺瀛╄ぐ鍐暰?
                    try:
                        with open(file_path, 'a') as f:
                            pass
                    except (IOError, PermissionError):
                        file_info["locked"] = True
                        # 闂傚倸鍊峰ù鍥敋瑜忛幑銏ゅ箛椤旇棄搴婇梺鐟邦嚟婵潧鐣烽弻銉︾厱闁斥晛鍟伴埊鏇㈡煕鎼粹槄鏀婚柕鍥у瀵粙顢曢～顓犳崟闂備浇妫勯崯浼村窗閺嶎厼钃熼柡鍥╁枎缁剁偞绻涢幋鐐寸殤闁哄棛濮撮—鍐Χ閸愩劌濮曠紓浣筋嚙閻楁挸顕ｇ拠娴嬫婵☆垱绮嶅Λ鍐ㄧ暦濮椻偓婵℃悂骞囬埡浣稿Е闂佸搫澶囬崜婵嬪箯閸涘瓨顥堟繛鎴炲笒娴滅偓绻濋棃娑欙紞闁搞倖娲橀妵鍕箳閹存繍浠奸梺缁樺姇閿曨亪寮婚妸鈺佺睄闁稿本绮嶉幉姗€姊虹粙娆惧剭闁告梹鍨甸～蹇涘传閸曟嚪鍥х倞鐟滃秹鈥栭崼銉︾厽閹兼番鍨归崵顒勬煕閵婏箑鈻曟鐐村灴婵偓闁绘ɑ鐗滈崰鏍箠閺嶎厼鐓涢柛鎰典簻楠?
                        try:
                            for proc in psutil.process_iter(['pid', 'name', 'open_files']):
                                try:
                                    for item in proc.info['open_files'] or []:
                                        if file_path.lower() in item.path.lower():
                                            diagnosis["cograg"]["processes"].append({
                                                "pid": proc.info['pid'],
                                                "name": proc.info['name'],
                                                "path": item.path
                                            })
                                except (psutil.NoSuchProcess, psutil.AccessDenied):
                                    continue
                        except Exception:
                            pass

                    diagnosis["cograg"]["files"].append(file_info)

        return diagnosis

    except ImportError:
        return {"error": "psutil module not installed", "message": "Install psutil to use this feature: pip install psutil"}
    except Exception as e:
        main_logger.error("Log message")
        return {"success": True, "message": "Operation completed"}

@app.delete("/databases/{database_name}")
async def delete_database_endpoint(database_name: str, user: dict = Depends(require_current_user)):
    """
    闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁嶉崟顒佹闂佺粯鍔曢顓犵不妤ｅ啯鐓冪憸婊堝礈濮樿鲸宕叉繛鎴欏灩瀹告繃銇勯幘鍗炵仼鐎殿喗婢樿灃闁绘﹢娼ф禒锕傛煕閺冣偓閻熴儵鎮鹃悜钘夌畾闂侇叏闄勯瀷闂傚倷绀侀幖顐⑽涢弮鍫濈闁规儼妫勯拑鐔兼煃閳轰礁鏆炲┑顖涙尦閺屾稑鈹戦崱妤婁紝闂佸搫妫崣鍐箖濡ゅ啯鍠嗛柛鏇ㄥ墮閻噣姊虹紒妯洪嚋缂佺姵鎹囬悰顕€宕卞☉妯肩潉闂佸壊鍋呯换鍕敊閹剧粯鈷戦柛娑橈攻婢跺嫰鏌涘鈧粻鏍闂佸啿鎼幊蹇涘煕閹达附鍋犳繛鎴炲坊閸嬫捇宕楅崨顓ф闂傚倷娴囬褎顨ラ幖浣瑰€舵慨妯挎硾缁犳椽鏌ｉ幒鏃€鍎眅rRAG闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁嶉崟顐㈢亰閻庡厜鍋撻柛鏇ㄥ墮娴犻亶姊虹悰鈥充壕闂?RAG闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁撻悩鍐蹭画闂侀潧顦弲婊堝磿閺傚簱鏀介柛灞剧閸熺偤鏌ｉ幒妤冪暫闁诡喗顨婂Λ鍐ㄢ槈濞嗘劕鏋戠紓浣哄亾閸庢娊濡堕幖浣歌摕闁挎繂顦崡鎶芥煟閹邦厾銈撮柛瀣崌閹筹繝濡堕崶鈺冨姸?

    Args:
        database_name: 闂傚倸鍊搁崐宄懊归崶褜娴栭柕濞炬櫆閸ゅ嫰鏌ょ粙璺ㄤ粵婵炲懐濮垫穱濠囧Χ閸屾矮澹曢梻浣风串缁蹭粙鎮樺璺虹闁告侗鍨遍崰鍡涙煕閺囥劌浜滃┑鈩冨▕濮婄粯鎷呯粵瀣秷閻庤娲橀敋闁宠绉瑰鎾閻樼绱柣搴ゎ潐濞叉牕煤閵娧冾棜?

    Returns:
        闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁嶉崟顒佹闂佺粯鍔曢顓犵不妤ｅ啯鐓冪憸婊堝礈濮樿鲸宕叉繛鎴欏灩瀹告繃銇勯幘璺烘瀾鐎规洖纾槐鎾存媴娴犲鎽甸柣銏╁灲缁绘繈鎮伴鍢夌喓浜搁弽褌澹曢梺姹囧灩閹测€斥枍濠婂牊鐓?
    """
    import gc
    import time

    try:
        main_logger.info("Log message")

        # 婵犵數濮撮惀澶愬级鎼存挸浜炬俊銈勭劍閸欏繘鏌熺紒銏犳灍闁稿孩顨呴妴鎺戭潩閿濆懍澹曢梻浣筋嚃閸垶鎮為敃鈧銉╁礋椤栨氨鐤€濡炪倖甯婇懗鍫曞焵椤掑澧存慨濠呮缁辨帒顫滈崱妯兼殽闂備胶绮〃鍛涘☉姘灊濠电姴娲﹂弲婵嬫煕鐏炵偓鐨戞い鏃€鍔欓弻锝嗘償閵忊懇濮囬柦鍐憾閹绠涢敐鍛睄闂佸搫鐬奸崰鏍€佸▎鎾村殟闁靛／灞拘ょ紓鍌氬€风欢锟犲窗濡も偓铻為柛鎰电厛閸ゆ洟鏌涢幘鑼妽鐎规洖顦甸弻鏇熺節韫囨稒顎嶅銈嗘崌缁犳牕顫忕紒妯诲濞撴凹鍨抽崝鍝ョ磽娴ｇ瓔鍤欓柣妤佹尭閻ｅ嘲鈹戦崱鈺佹倯婵犮垼娉涢敃锕傚礉?
        if not database_name or database_name in ['.', '..'] or '/' in database_name or '\\' in database_name:
            return {"success": False, "message": "Invalid database name"}

        # 缂傚倸鍊搁崐鎼佸磹閻戣姤鍊块柨鏇炲€堕埀顒€鍟村畷濂稿Ψ椤旇姤娅嗛梺鍝勵槸閻楀嫰宕濆澶婄煑闊洦姊荤弧鈧梻鍌氱墛缁嬫垿顢旈埡鍛厱闁哄啫鍊归弳鈺冪磼鏉堛劌绗氭繛鐓庣箻婵℃悂鏁傞幆褍娈ラ梻鍌欑窔濞佳兾涘▎鎴炴殰闁炽儱纾弳锕傛煏婵炑€鍋撻柛瀣尭閳藉鈻庡Ο鐓庡Ш闁荤喐绮庢晶妤呭垂閸噮娼栨繛宸簻閹硅埖銇勯幘妤€瀚惁婊堟⒒娴ｄ警鐒炬い鎴濇楠炴垿宕堕鈧拑鐔兼煥閻斿搫孝闂佸崬娲︾换婵嬪垂椤愩垹顫嶉梺鍝勬噽鐎氭椉闂傚倸鍊峰ù鍥敋瑜庨〃銉х矙閸柭も偓鍧楁⒑椤掆偓缁夊澹曠紒妯圭箚妞ゆ牗鑹鹃幃鎴炪亜閹邦亞鐭欓柡灞炬礃缁旂喖顢涘顓炴闂佹寧绋掔换鍫濐潖閾忚鍠嗛柛鏇ㄥ亜婵垻绱掗崜褑妾搁柛娆忓暣閻?
        print("Log message")
        cleared_instances = []

        if database_name in hyperrag_instances:
            instance = hyperrag_instances[database_name]
            # 闂傚倸鍊峰ù鍥敋瑜忛幑銏ゅ箛椤旇棄搴婇梺鐟邦嚟婵潧鐣烽弻銉︾厱闁斥晛鍟伴埊鏇㈡煕鎼粹槄鏀婚柕鍥у瀵粙濡歌閻撲線鏌ｆ惔銏犲毈闁告挾鍠栧璇测槈閵忕姷鐤€闂佺绻愰幗婊堝礄瑜版帗鈷戦柛婵嗗椤ユ粎绱掔紒姗堣€挎鐐插暙铻栭柛娑卞幗瀹撳秴顪冮妶鍡樺暗闁稿顭囬崚鎺曨槾缂佽鲸鎸婚幏鍛存偩鐏炵晫澧梻浣侯焾濞寸兘寮繝姘卞祦闁糕剝绋戠粈鍐┿亜閺冨洤浜规い锔芥緲椤啴濡堕崱妤冪懆闂佺顑呭Λ娆戔偓闈涖偢瀵挳濮€閳锯偓閹锋椽姊洪悡搴綗闁稿﹥娲樼粋鎺戭煥閸曨亞绠氬銈嗗姧缁插潡骞婇崶鈹惧亾濞堝灝鏋涙い顓犲厴楠炲啴濮€椤厾鍓ㄦ繛杈剧到濠€杈ㄧ濞嗘挻鈷掑ù锝呮啞閹牊绻涢弶鎴濃偓鍦矉瀹ュ鍊烽柣銏㈡暩閻掑ジ姊洪崨濠冨闁稿鍋撻梺琛″亾濞寸姴顑嗛悡鍐煏婢跺牆鍔氶柡鍡涗憾閺屽秷顧侀柛鎾寸懅缁辩偞绻濋崶褏鐣哄┑鈽嗗灥椤曆呮閻愮儤鍊堕柣鎰問閻掓儳霉濠婂懎浜剧紒缁樼洴楠炲鎮滈崱鏇犳／婵＄偑鍊曠换鎰偓姘倐閹虫捇骞愭惔娑楃盎闂婎偄娲﹂幐鐐櫠濞戙垺鐓?
            if hasattr(instance, '_cleanup'):
                try:
                    instance._cleanup()
                    print("Log message")
                except Exception as e:
                    print("Log message")

            del hyperrag_instances[database_name]
            cleared_instances.append(f"HyperRAG({database_name})")
            main_logger.info("Log message")
            print("Log message")

        if database_name in cograg_instances:
            instance = cograg_instances[database_name]
            # 闂傚倸鍊峰ù鍥敋瑜忛幑銏ゅ箛椤旇棄搴婇梺鐟邦嚟婵潧鐣烽弻銉︾厱闁斥晛鍟伴埊鏇㈡煕鎼粹槄鏀婚柕鍥у瀵粙濡歌閻撲線鏌ｆ惔銏犲毈闁告挾鍠栧璇测槈閵忕姷鐤€闂佺绻愰幗婊堝礄瑜版帗鈷戦柛婵嗗椤ユ粎绱掔紒姗堣€挎鐐插暙铻栭柛娑卞幗瀹撳秴顪冮妶鍡樺暗闁稿顭囬崚鎺曨槾缂佽鲸鎸婚幏鍛存偩鐏炵晫澧梻浣侯焾濞寸兘寮繝姘卞祦闁糕剝绋戠粈鍐┿亜閺冨洤浜规い锔芥緲椤啴濡堕崱妤冪懆闂佺顑呭Λ娆戔偓闈涖偢瀵挳濮€閳锯偓閹锋椽姊洪悡搴綗闁稿﹥娲樼粋鎺戭煥閸曨亞绠氬銈嗗姧缁插潡骞婇崶鈹惧亾濞堝灝鏋涙い顓犲厴楠炲啴濮€椤厾鍓ㄦ繛杈剧到濠€杈ㄧ濞嗘挻鈷掑ù锝呮啞閹牊绻涢弶鎴濃偓鍦矉瀹ュ鍊烽柣銏㈡暩閻掑ジ姊洪崨濠冨闁稿鍋撻梺琛″亾濞寸姴顑嗛悡鍐煏婢跺牆鍔氶柡鍡涗憾閺屽秷顧侀柛鎾寸懅缁辩偞绻濋崶褏鐣哄┑鈽嗗灥椤曆呮閻愮儤鍊堕柣鎰問閻掓儳霉濠婂懎浜剧紒缁樼洴楠炲鎮滈崱鏇犳／婵＄偑鍊曠换鎰偓姘倐閹虫捇骞愭惔娑楃盎闂婎偄娲﹂幐鐐櫠濞戙垺鐓?
            if hasattr(instance, '_cleanup'):
                try:
                    instance._cleanup()
                    print("Log message")
                except Exception as e:
                    print("Log message")

            del cograg_instances[database_name]
            cleared_instances.append(f"Cog-RAG({database_name})")
            main_logger.info("Log message")
            print("Log message")

        # 闂傚倷娴囬褏鈧稈鏅犻、娆撳冀椤撶偟鐛ラ梺鍝勭▉閸樿偐绮荤憴鍕╀簻闁规澘澧庨悾閬嶆煛閸曗晛鍔滃ǎ鍥э躬婵″爼宕ㄩ鍏碱仩闂備焦鎮堕崝宀勫磹閸ф钃熸繛鎴欏灩缁犳盯鏌嶆潪鎵槮妞ゎ剙顦辩槐鎾存媴闂堟稑惟闂佹悶鍔嬬划娆忣嚕鐠囨祴妲堥柕蹇曞閵娧勫枑鐎广儱妫涢々鐑芥煥閺囩偛鈧綊鎮?
        gc.collect()
        time.sleep(0.5)  # 缂傚倸鍊搁崐鎼佸磹閹间礁纾归柣鎴ｅГ閸婂潡鏌ㄩ弴鐐测偓褰掑磻閿涘嫭鍠愰柡鍐ㄧ墕閽冪喖鏌涢鐔稿櫚闁稿鎹囧Λ鍐ㄢ槈濞嗘劕鏋戠紓浣哄亾閸庢娊濡堕幖浣歌摕闁挎繂顦Λ姗€鏌熺粙鍧楊€楅柡鍡楃墕椤啴濡甸娆戭槮婵炶绠撻崺娑㈠箳濡や胶鍘遍柣蹇曞仜婢т粙鍩婇弴銏″€堕煫鍥ュ劤閻ｇ敻鏌＄仦鍓ф创闁轰焦鍔欏畷鍗炍熼崫鍕暘闂佽瀛╅鏍窗閹捐绀夐柟杈惧瀹撲線鏌熸潏鍓х暠缂佺姵绋掗妵鍕棘閹稿孩鍎撴繛瀛樼矎婵倗鎹?

        if cleared_instances:
            print("Log message")

        # 缂傚倸鍊搁崐鎼佸磹閻戣姤鍊块柨鏇炲€堕埀顒€鍟村畷濂稿Ψ閿曗偓閸擃剟鏌ｈ箛鏇炰户闁稿鎹囧畷锝堢疀閺冨倻鐦堥梻鍌氱墛缁嬫垿顢旈埡鍛厱闁哄啫鍊归弳鈺冪磼鏉堛劌绗氭繛鐓庣箻婵℃悂濡烽绛嬫闂傚倷鑳堕幊鎾汇€冩惔銊ョ；濠电姴鍊婚弳锔芥叏濡炶浜惧銈冨灪濡啫鐣烽妸鈺婃晩缂佹稑顑呴幃鍛存⒒閸屾艾鈧嘲霉閸パ屾禆闁靛ň鏅滈崵鍕煠缁嬭法浠涙繛鍛У娣囧﹪濡堕崒姘闂備椒绱徊浠嬫倶濮樿泛绠柛娑卞灡閸犲棝鏌涢弴銊ヤ簻濠碘剝濞婂缁樻媴缁涘缍堥梺绋垮婵炲﹪骞冮妷锔鹃檮缂佸娉曢悾娲⒑閸撴彃浜濇繛鍙夌墵閻涱噣濮€閳ヨ尙绠氶梺闈涚墕鐎氼垶宕楀畝鈧幉鎼佹偋閸垻鐓夊┑顔硷攻濡炶棄鐣烽妸锔剧瘈闁稿本绮犻崕灞解攽閻樺灚鏆╅柛瀣姍瀹曟垿骞橀弬銉︽杸闂佺粯鍔曞鍫曞闯瑜版帗鈷戦悽顖ｅ枤閸掔増銇勯弴顏嗙М妞ゃ垺娲熼弫鍌炴寠婢跺缍嶉梻鍌欑婢瑰﹪宕戦崨顖涘床闁告洦鍨板洿闂佹寧娲栭崐褰掓偂?
        print("Log message")
        result = db_manager.delete_database(database_name)

        # 闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁撻悩鑼槷闂佸搫娲ㄦ慨鐑芥儗閹剧粯鐓熼柕蹇嬪焺閺嗩垶鏌涚€ｎ偅灏柍缁樻崌瀹曞綊顢欓悾灞奸偗闂傚倷绀佸﹢閬嶅煕閸儱纾诲┑鐘插€婚弳锕傛煕濠靛棗鐝嬮柡鍐ㄧ墕瀹告繃銇勯幘璺轰户闁逞屽墻閸欏啫顫忓ú顏勫窛濠电姴鍊搁～鍥⒑閸涘﹥鐓ョ紒澶婄埣閹崇偤鏌嗗鍜佹綂闂侀潧鐗嗗Λ娑㈠储闁秵鈷戦梻鍫熷喕缁憋繝鏌涢幇灞藉婵即姊?
        gc.collect()

        # 缂傚倸鍊搁崐鎼佸磹閻戣姤鍊块柨鏇炲€堕埀顒€鍟村畷濂稿Ψ閿曗偓娴狀參妫呴銏″婵﹤缍婂畷锝堢疀閺冨倻鐦堥梻鍌氱墛缁嬫垿顢旈埡鍛厱闁哄啫鍊归弳鈺冪磼鏉堛劌娴€规洩绲借灒闁告繂瀚妶顕€鏌ｆ惔銈庢綈婵炴祴鏅濈槐鐐寸瑹閳ь剟鎮伴閿亾閿濆骸鏋熼柡鍛矒閺岋綁鎮㈢喊杈ㄦ婵犮垼顫夊ú妯兼崲濞戙垹绠ｉ柣鎰嚟閸欏棝姊洪幖鐐插闁活偒鏋cket闂傚倸鍊搁崐鎼佸磹妞嬪孩顐介柨鐔哄Т绾惧鏌涘☉鍗炲季婵炲皷鏅犻弻鏇熺箾閻愵剚鐝曢梺?
        try:
            await manager.broadcast_json({
                "type": "database_deleted",
                "database_name": database_name,
                "success": result.get("success", False),
                "timestamp": datetime.now().isoformat()
            })
            main_logger.info("Log message")
            print("Log message")
        except Exception as e:
            main_logger.warning("Log message")
            print("Log message")

        # 濠电姷鏁告慨鐑藉极閹间礁纾块柟瀵稿Х缁€濠囨煃瑜滈崜姘跺Φ閸曨垰鍗抽柛鈩冾殔椤忣亪鏌涘▎蹇曠闁哄矉缍侀獮鍥敆閸屾稑瀣€闂備線鈧偛鑻晶顖炴偨椤栨せ鍋撳畷鍥ㄦ闂侀潧艌閺呪晠寮鍡欑闁瑰鍊戝璺虹；闁瑰墽绮崐鐑芥煟閹寸儐鐒介柛妯圭矙濮婃椽妫冨☉杈╁姼闂佺閰ｆ禍鍫曘€侀弮鍫濈厸闁告侗鍠氶崢浠嬫⒑闂堟稓澧曢柟鍐查叄椤㈡棃顢旈崱娆戯紲濠德板€曢崯顐﹀几閺冨牊鐓冪憸婊堝礈閵娧冪筏婵炲樊浜滈悿鐐箾閸℃ê鐏︾€规洘鐓￠弻娑㈠焺閸愵亖濮囬梺缁樻尰閻燂箓濡甸崟顖氱閻犻缚妗ㄩ幋鐑芥⒑閸涘鎴犳暜閻愬灚顫曢柟鎹愵嚙绾惧吋绻涢崱妯虹仴濠碘€茬矙濮婃椽宕烽褏鍔稿銈庡幘閸忔﹢鐛崘銊庣喓鎷犻懠顒傜嵁闂佽鍑界紞鍡涘礂濮椻偓瀵?
        result["cleared_instances"] = cleared_instances

        return result

    except Exception as e:
        main_logger.error("Log message")
        print("Log message")
        return {"success": True, "message": "Operation completed"}

@app.post("/files/embed")
async def embed_files(request: FileEmbedRequest, user: dict = Depends(require_current_user)):
    """
    闂傚倸鍊搁崐椋庣矆娴ｈ櫣绀婂┑鐘插亞閻掔晫鎲歌箛鏇燁潟闁绘劕顕弧鈧梺鎼炲劀閸ヮ煉绱梻鍌欑閹诧紕鎹㈤崒婧惧亾濮樼厧娅嶇€殿喗濞婃俊鑸靛緞鐎ｎ亖鍋撻崼鏇熺厽闁归偊鍨伴悡鎰亜閵夈儺妲洪柍褜鍓氶鏍窗濡や胶绠惧┑鐘叉搐閽冪喖鏌ㄩ悢鍝勑㈢痪鎯у悑閹便劌顫滈崱妤€绠瑰銈忚吂閺呯姴顫忓ú顏咁棃婵炴垶鐟Λ鐐烘⒑缁嬪尅宸ラ柣蹇旂箞閹儳鐣￠柇锔藉兊闂佸吋鎮傚褔宕滈鍕€垫繛鍫濈仢閺嬬喖鏌涘▎蹇嬪仱rRAG
    """
    if not HYPERRAG_AVAILABLE:
        raise HTTPException(status_code=500, detail="HyperRAG is not available")
    
    print(f"\n{'='*50}")
    print("Log message")
    print("Log message")
    print(f"{'='*50}")
    
    results = []
    
    try:
        database_name = require_database_access(database_name, user)
        consume_document_quota_if_needed(user, len(request.file_ids))
        await preflight_hyperrag_api_services()

        for i, file_id in enumerate(request.file_ids):
            file_info = None
            database_name = None
            content = None
            try:
                print("Log message")
                
                # 闂傚倸鍊搁崐椋庣矆娓氣偓楠炴牠顢曢埛姘そ婵¤埖寰勭€ｎ亙妲愰梻渚€娼ц墝闁哄懏鐩幏鎴︽偄鐏忎焦鏂€闂佺粯锚瀵爼骞栭幇顓濈箚妞ゆ劧缍囬懓鍧楁煛鐏炲墽娲村┑锛勫厴椤㈡盯鎮欓幖顓涘亾瀹ュ拋娓婚柕鍫濇婵啰绱掗鐣屾噰鐎殿喖顭烽弫鎰板川閸屾粌鏋涚€规洖缍婇、娆撳箚瑜嶇紓姘舵⒒閸屾瑧绐旈柍褜鍓涢崑娑㈡嚐椤栫偛鍌ㄩ柛娑橈梗缁诲棝鏌ｉ幇顓熺稇缂佹う鍥ㄧ厵鐎瑰嫭澹嗙粔娲煙椤斿搫鐏紒顔界懅閹瑰嫰濡歌瀹撲線姊婚崒娆戭槮闁规祴鈧秮娲晝閸屾艾鍋嶆繛瀵稿Т椤戝懐澹曡ぐ鎺撶厽闁归偊鍘鹃妶瀛樹繆?
                print("Log message")
                file_manager.update_file_status(file_id, "processing")
                
                # 闂傚倸鍊搁崐椋庣矆娓氣偓瀹曘儳鈧綆鍠栫壕鍧楁煙閹増顥夐幖鏉戯躬閺屻倝鎳濋幍顔肩墯婵炲瓨绮岀紞濠囧蓟濞戙垹唯妞ゆ梻鍘ч～鈺佲攽閳藉棗浜濋柨鏇樺灲瀵鈽夐姀鐘栥劍銇勯弽顐沪妞ゅ骸绉撮—鍐Χ閸℃顫戝┑鈽嗗亜鐎氼垵銇愭笟鈧娲箹閻愭彃濮风紓浣藉蔼婵倝寮查崼鏇炵闁?
                print("Log message")
                file_info = file_manager.get_file_by_id(file_id, owner_user_id=user.get("id"), include_legacy=True)
                if not file_info:
                    error_msg = "Operation failed"
                    print(f"[ERROR] {error_msg}")
                    results.append({
                        "file_id": file_id,
                        "status": "error",
                        "filename": getattr(file, "filename", "unknown"),
                    })
                    continue
                
                print("Log message")
                
                # 婵犵數濮烽弫鎼佸磻閻樿绠垫い蹇撴缁€濠囨煃瑜滈崜姘辨崲濞戞瑥绶為悗锝庡亞椤︿即鎮楀▓鍨珮闁稿锕ユ穱濠囨嚋闂堟稓绐炴繝鐢靛Т閸犳艾螞閻斿吋鈷掑ù锝堫潐閸嬬娀鏌涙惔鈽嗙吋婵﹣绮欏畷鐔碱敍閿濆棙娅囧┑鐐差嚟婵挳顢栭崱娑樼９闁汇垹鎲￠悡鐔兼煏韫囨洖啸濞寸姵鐩弻娑㈠Χ閸屾矮澹曠紓鍌氬€搁崐鐑芥⒔瀹ュ绀夌€广儱顦伴崑鍌炴煥閻斿搫孝缂佺姵宀搁弻娑㈠箛闂堟稒鐏堢紓浣插亾閻庯綆鍋佹禍婊堟煙閸濆嫮肖闁告柨绉甸妵鍕棘鐠恒剱褎鎱ㄦ繝鍐┿仢闁诡喚鍏橀幃褔宕奸敐鍥舵敤濠电姵顔栭崰妤勫綘闂佸憡姊归崹鍨嚕?
                database_name = file_info["database_name"]
                print("Log message")
                rag = get_or_create_hyperrag(
                    database_name,
                    chunk_size=request.chunk_size,
                    chunk_overlap=request.chunk_overlap,
                )
                
                # 闂傚倸鍊峰ù鍥х暦閸偅鍙忛柡澶嬪殮濞差亜鐓涢柛婊€鐒﹂弲顏堟偡濠婂嫬鐏村┑锛勬暬楠炲洭寮剁捄銊モ偓鐐差渻閵堝棗鍧婇柛瀣尰娣囧﹪顢曢敐蹇氣偓鍧楁煛鐏炲墽娲村┑锛勫厴椤㈡盯鎮欓幖顓涘亾瀹ュ拋娓婚柕鍫濇婵啰绱掗鐣屾噰鐎殿喛顕ч埥澶愬閻樼數鏉告俊鐐€栫敮濠勭矆娴ｇ硶鏋?
                print("Log message")
                content = await file_manager.read_file_content(file_info["file_path"])
                print("Log message")
                
                # 闂傚倸鍊搁崐椋庣矆娴ｉ潻鑰块弶鍫氭櫅閸ㄦ繃銇勯弽銊х煁闁哄棙绮撻弻鐔兼倻濮楀棙鐣堕梺娲诲幗椤ㄥ﹪寮诲☉銏犵労闁告劦浜栧Σ鍫㈢磽娴ｆ彃浜鹃梺绯曞墲缁嬫帡鎮￠悢鐑樺枑鐎广儱娲﹂～鏇犵棯椤撶偛鍔歳RAG
                print("Log message")
                await rag.ainsert(content)
                print("Log message")
                
                # 闂傚倸鍊搁崐椋庣矆娓氣偓楠炴牠顢曢埛姘そ婵¤埖寰勭€ｎ亙妲愰梻渚€娼ц墝闁哄懏鐩幏鎴︽偄鐏忎焦鏂€闂佺粯锚瀵爼骞栭幇顓濈箚妞ゆ劧缍囬懓鍧楁煛鐏炲墽娲村┑锛勫厴椤㈡盯鎮欓幖顓涘亾瀹ュ拋娓婚柕鍫濇婵啰绱掗鐣屾噰鐎殿喖顭烽弫鎰板川閸屾粌鏋涚€规洖缍婇、娆撳箚瑜嶇紓姘舵⒒閸屾瑧绐旈柍褜鍓涢崑娑㈡嚐椤栫偛鍌ㄩ柛娑橈梗缁诲棝鏌ｉ幇顓熺稇缂佹う鍥ㄧ厵鐎瑰嫭澹嗙粔娲煙椤斿搫鐏紒楦垮Г瀵板嫭绻濋崘鈺冨綃闂傚倸鍊风粈浣革耿鏉堚晛鍨濇い鏍ㄧ矋閺嗘粓鏌ｉ幇顒佹儓閸ユ挳姊哄Ч鍥х仼闁硅绻濋幃?
                file_manager.update_file_status(file_id, "embedded")
                
                results.append({
                    "file_id": file_id,
                    "filename": file_info["filename"],
                    "database_name": database_name,
                    "status": "embedded"
                })
                
                print("Log message")
                
            except Exception as e:
                # 闂傚倸鍊搁崐椋庣矆娓氣偓楠炴牠顢曢埛姘そ婵¤埖寰勭€ｎ亙妲愰梻渚€娼ц墝闁哄懏鐩幏鎴︽偄鐏忎焦鏂€闂佺粯锚瀵爼骞栭幇顓濈箚妞ゆ劧缍囬懓鍧楁煛鐏炲墽娲村┑锛勫厴椤㈡盯鎮欓幖顓涘亾瀹ュ拋娓婚柕鍫濇婵啰绱掗鐣屾噰鐎殿喖顭烽弫鎰板川閸屾粌鏋涚€规洖缍婇、娆撳箚瑜嶇紓姘舵⒒閸屾瑧绐旈柍褜鍓涢崑娑㈡嚐椤栫偛鍌ㄩ柛娑橈梗缁诲棝鏌ｉ幇顓熺稇缂佹う鍥ㄧ厵鐎瑰嫭澹嗙粔娲煙椤斿搫鐏茬€规洘顨婇幊鏍煛娴ｅ憡杈堟繝?
                detailed_error = log_detailed_exception(
                    main_logger,
                    "Embedding API test failed",
                    e,
                    {
                        "file_id": file_id,
                        "filename": file_info.get("filename") if "file_info" in locals() and file_info else None,
                        "database_name": locals().get("database_name"),
                        "rag_system": request.rag_system,
                        "chunk_size": request.chunk_size,
                        "chunk_overlap": request.chunk_overlap,
                        "content_chars": len(content) if "content" in locals() else None,
                        "runtime_settings": get_runtime_settings_context(),
                    },
                )
                user_friendly_error = extract_user_friendly_error(detailed_error)
                error_msg = "Operation failed"
                print(f"[ERROR] {error_msg}")
                file_manager.update_file_status(file_id, "error", user_friendly_error)
                
                results.append({
                    "file_id": file_id,
                    "status": "error",
                    "error": user_friendly_error,
                    "detailed_error": detailed_error[:500]
                })
        
        successful = len([r for r in results if r.get('status') == 'embedded'])
        print("Log message")
        print(f"{'='*50}")
        
        return {"embedded_files": results}

    except Exception as e:
        detailed_error = log_detailed_exception(
            main_logger,
            "Embedding API test failed",
            e,
            {
                "file_ids": request.file_ids,
                "rag_system": request.rag_system,
                "target_database": request.target_database,
                "chunk_size": request.chunk_size,
                "chunk_overlap": request.chunk_overlap,
                "runtime_settings": get_runtime_settings_context(),
            },
        )
        error_msg = "Operation failed"
        print(f"[ERROR] {error_msg}")
        raise HTTPException(status_code=500, detail=extract_user_friendly_error(detailed_error))

@app.post("/cache/clear")
async def clear_hyperrag_cache():
    """
    濠电姷鏁告慨鐑藉极閹间礁纾婚柣鎰惈缁犱即鏌熼梻瀵割槮缂佺姷濮垫穱濠囶敍濠靛嫧鍋撻埀顒勬煛?HyperRAG 闂傚倸鍊峰ù鍥敋瑜庨〃銉х矙閸柭も偓鍧楁⒑椤掆偓缁夊澹曠紒妯圭箚妞ゆ牗鑹鹃幃鎴炪亜閹邦亞鐭欓柡灞炬礃缁旂喖顢涘顓炴闂佹寧绋掔换鍫濐潖閾忚鍠嗛柛鏇ㄥ亜婵垻绱掗崜褑妾搁柛娆忓暣閻涱喖螖閸涱喖浜圭紓鍌欑劍椤洭宕ｉ崱妞绘斀闁绘劖娼欓悘锔姐亜椤撶偟澧㈤柍褜鍓氱喊宥嗙珶閸℃稑鐒垫い鎺戝枤濞兼劙鏌熼鐓庘偓鍦矉瀹ュ洦宕夐柧蹇氼潐濞堟儳鈹戦绛嬬劸婵炲鐩弻瀣炊椤掍胶鍘搁梺鎼炲劗閺呮稒绂掗敂濮愪簻闊洦娲栭弸娑欐叏婵犲啯銇濈€规洦鍋婂畷鐔碱敃閻旇渹澹曢梺鑽ゅ枛閸嬪﹪鎮㈤崱妯诲弿婵＄偠顕ф禍楣冩倵鐟欏嫭绀€缂傚秴锕ら悾鐑芥晸閻樺啿鈧鏌涢埄鍐炬畷闁伙絽銈稿缁樻媴閸涘﹤鏆堢紓浣筋嚙閸婂鍩€椤掍礁鍤柛锝忕到椤曪綁宕奸弴鐔风檮婵犮垼娉涢悧鍐磻?
    """
    global hyperrag_instances
    cleared_count = len(hyperrag_instances)
    hyperrag_instances = {}
    main_logger.info("Log message")
    return {"success": True, "message": f"Knowledge base {kb_name} deleted"}
# 闂傚倸鍊搁崐椋庣矆娓氣偓婵″爼骞栨担鈧径鎰閻犲洤寮舵潏鍫ユ⒑閸濆嫷妲哥紒銊ュ船鍗遍柛顐犲劜閻撴盯鏌涚仦鍙ョ繁闁稿簺鍎叉穱濠囨嚑妫版繃缍堟繛锝呮搐閿曨亪銆侀弴銏″亜闁告稑锕﹁ぐ鍫㈢磽閸屾瑨鍏屽┑顔炬暩缁瑩骞嬮敐鍥︾胺闂傚倷绶氶埀顒傚仜閼活垱鏅堕幘顔界厸鐎光偓鐎ｎ剛袦闂佽鍠楅悷鈺佺暦閿濆棗绶炴俊顖涙た濡冣攽閻樺灚鏆╅柛瀣洴楠炲﹨绠涢弴鐔告闂佽法鍠撴慨鎾几娴ｈ　鍋撻獮鍨姎婵炶绲介埢浠嬵敂閸喓鍘介梺鎸庣箓閹冲繐锕㈤悧鍫涗簻闁哄啠鍋撻柛銊ョ仢椤繐煤椤忓嫪绱堕梺鍛婃处閸嬪懎鈻撹濮婅櫣绮欓幐搴℃敪婵炲瓨绮犻崜鐔肩嵁閹达箑顫呴柕鍫濇噽閻嫰姊洪崜鎻掍簽闁哥姵鎹囧畷婵嬫濞戞帗鏂€濡炪倖姊婚悡顐︻敂閸℃妫滃銈嗘尵婵攱绋夊澶嬬厸闁割偅绋堥崑鎾诲传缁涘朝cket闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁撻悩鍐蹭画闂佹寧娲栭崐鎼佸垂閸岀偞鐓曠憸搴ㄣ€冮崨瀛樺€?
class WebSocketLogHandler(logging.Handler):
    def __init__(self, connection_manager):
        super().__init__()
        self.connection_manager = connection_manager

    def emit(self, record):
        try:
            log_message = self.format(record)
            # 婵犵數濮烽弫鎼佸磻閻樿绠垫い蹇撴缁€濠囨煃瑜滈崜姘辨崲濞戞瑥绶為悗锝庡亞椤︿即鎮楀▓鍨珮闁稿锕ㄥΛ鐔封攽閳╁啫鍔ら柛搴ｎ棁_str婵犵數濮烽弫鍛婃叏娴兼潙鍨傞柣鎾崇岸閺嬫牗绻涢幋鐐茬劰闁稿鎸搁～婵嬫偂鎼淬垻褰庢俊銈囧Х閸嬫盯宕婊勫床婵犻潧顑呴悙濠勬喐韫囨稒鍋傞柟杈鹃檮閳锋垹绱掔€ｎ厽纭剁紒鐘崇叀閺屻劑寮村Ο铏逛患闂佷紮绲块崗姗€骞冮埡鍐╁珰闁圭粯甯為悰鈺備繆閻愵亜鈧牠骞愭ィ鍐ㄧ獥閹兼番鍔岀粈鍫ユ煟閵忕姵鍟為柍閿嬪浮閺屾稓浠﹂崜褎鍣紓浣哄У濞碱摨code闂傚倸鍊峰ù鍥敋瑜忛埀顒佺▓閺呮繄鍒掑▎鎾崇婵＄偛鐨烽崑鎾诲礃椤斿ジ鍞堕梺闈涱檧婵″洭宕㈡禒瀣拺闂傚牊渚楅悞楣冩煕鎼淬劋鎲炬い銏℃椤㈡棃宕ㄩ鍌滅暰婵＄偑鍊栭崝妤呭窗閹邦兘鏋嶉柛顐犲灮绾惧ジ鏌ｅΟ铏癸紞闁宠棄顦甸幗鍫曞冀椤€崇秺閺佹劙宕堕妸褝绱涢梻渚€娼чˇ顐﹀疾濠婂牊鍋?            safe_message = safe_str(log_message)
            # 闂傚倷娴囬褏鈧稈鏅犻、娆撳冀椤撶偟鐛ラ梺鍝勭▉閸樿偐澹曢崷顓熷枑闁绘鐗嗙粭姘舵煟閹惧瓨绀冪紒缁樼洴瀹曞崬螣閸濆嫷娼撻梻浣筋嚙缁绘垿骞愰幎钘夎摕鐎广儱鐗滃銊╂⒑缁嬭法绠查柣鈺婂灦楠炲啴鎮欓悜妯绘珖闂侀€炲苯澧查柣蹇擃儔濮婃椽宕橀崣澶嬪創闁诲孩鍑归崳锝夊箖閸ф鐒垫い鎺嗗亾闁宠鍨堕獮濠囨煕婵犲啯宕岄柟铏殘閹瑰嫰鎮滃Ο鑽ゆ闂?            loop = asyncio.get_running_loop()
            loop.create_task(self.connection_manager.send_log_message({
                "type": "log",
                "level": record.levelname,
                "message": safe_message,
                "timestamp": record.created,
                "logger_name": record.name
            }))
        except Exception:
            pass  # 闂傚倸鍊搁崐鎼佸磹妞嬪孩顐介柨鐔哄Т缁€鍫熺箾閸℃ɑ灏伴柛濠呭煐缁绘繈妫冨☉鍗炲壈闂佺琚崝鎴﹀蓟閺囥垹閱囨繝鍨姈绗戠紓鍌欑贰閸嬪嫮绮旇ぐ鎺戣摕闁哄洨鍠庣欢鐐烘煕椤愶絿绠撳┑顔哄灮缁辨挻鎷呴崫鍕戭剚绻涙径瀣创闁炽儻濡囬幑鍕Ω閿曗偓绾绢垶姊洪崨濠勭畵閻庢岸鏀辩€靛ジ鍩€椤掑嫭鈷掑ù锝囩摂閸ゅ啴鏌涢悩宕囧⒌闁轰礁鍟撮、鏃堝礋椤撶喐顔曢梻浣筋潐閸庣厧螞閸曨剙鍔旈梻鍌欑窔濞佳団€﹂崼銉ョ？闁哄被鍎洪弫濠囨煕閵夘喖澧柍閿嬪笒閳规垿鎮╅弻銉偓妤€顭胯閸ㄥ爼寮婚敓鐘插窛妞ゅ繐鎳忛悵姘舵⒑鐠団€虫灈缂傚秴锕ら悾鐑藉箚闁附顎囨繝鐢靛仜閻楁粓宕圭捄渚綎婵炲樊浜滃婵嗏攽閻樻彃顏柣锝囨暩缁辨挻鎷呴崜鍙壭︾紒鍓ц檸閸欏啴宕洪埀顒併亜閹烘垵顏繛鎳峰洦鐓熸い鎺戝暙娴滃綊鏌涢幒鎾崇瑨闁宠閰ｉ獮瀣棘婢剁顥氶梻浣瑰缁诲倻鑺遍懖鈺勫С闁伙絽鐬煎Λ?

# 闂傚倸鍊搁崐椋庣矆娓氣偓婵″爼骞栨担鈧径鎰閻犲洤寮舵潏鍫ユ⒑閸濆嫷妲哥紒銊ュ船鍗遍柛顐犲劜閻撴盯鏌涚仦鍙ョ繁闁稿簺鍎叉穱濠囧箵閹烘捁纭€缂備浇椴哥敮妤冪箔閻斿摜绡€闁搞儺鐓堥埀顒€绉归幃妤呭垂椤愶絿鍑￠柣搴㈢濠㈡﹢鎮鹃悜鑺ュ亜缁炬媽椴搁弲锝夋⒑缂佹ɑ鐓ラ柣銊︾箞瀹曟垿骞樼紒妯衡偓鐑芥煟閹寸儐鐒介柛姗€浜跺娲箰鎼达絿鐣靛┑鐐茬湴閸旀垼妫熷銈嗘磵閸嬫挻鎱ㄦ繝鍛仩婵炴垹鏁诲畷顏呮媴閸︻厾啸濠电姷鏁搁崑娑橆嚕閸撲焦宕查柛顐犲劜閸嬫ɑ銇勯弮鍌楁嫛闁搞倖娲滈埀顒傛嚀鐎氼噣鎮ч悳鐠介梻鍌氬€峰ù鍥х暦閸偅鍙忛柡澶嬪殮濞差亜围闁搞儮鏅濋ˇ顖炴⒑閸濆嫮鈻夐柛妯圭矙閹繝寮撮悢铏圭槇婵犵數濮撮崐鎼佸汲閵忋倖鍊垫慨姗嗗亜瀹撳棝鏌＄仦鍓р槈闁宠閰ｉ獮瀣攽閸涱収妫滅紓鍌氬€风粈渚€宕愰崷顓熸殰闁炽儲鍓氶崵鏇灻归悩宸剾闁轰礁妫濋弻娑氫沪閸撗呯厒闂佺锕ユ繛濠傤潖?
class WebSocketStreamHandler:
    def __init__(self, connection_manager, stream_type="stdout"):
        self.connection_manager = connection_manager
        self.stream_type = stream_type
        self.original_stream = sys.stdout if stream_type == "stdout" else sys.stderr
        
    def write(self, message):
        try:
            # 闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁撻悩鍐叉疄婵°倧绲介崯顐も偓姘槹閵囧嫰骞掗崱妞惧婵＄偑鍊ゆ禍婊堝疮閺夋垹鏆﹂柟鐑橆殕閸婄兘鏌ょ喊鍗炲⒒婵¤尙澧楃换婵嬫偨闂堟稐绮跺┑鈽嗗亝椤ㄥ牓骞戦姀銈呯疀妞ゆ帒顦▓銊╂⒑鐟欏嫬鍔跺┑顔哄€濋幃锟犲即閻斿墎绠氬銈嗙墬缁瞼鏁崼鏇熺厸閻庯綆浜妤呮煃?
            self.original_stream.write(message)
            self.original_stream.flush()

            # 闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁撻悩鍐蹭画闂佹寧娲栭崐鎼佸垂閸岀偞鐓曠憸搴ㄣ€冮崨瀛樺€块柛顭戝亖娴滄粓鏌熸潏鍓хɑ缁绢叀鍩栭妵鍕晜閼测晝鏆ら梺鍝勬湰閻╊垶宕洪埄鍐懝闁搞儜鍐炬經ebSocket闂傚倸鍊搁崐鐑芥倿閿旈敮鍋撶粭娑樻噽閻瑩鏌熸潏楣冩闁稿顑夐弻娑㈠焺閸愵亗鈧帞鈧鎸风欢姘跺蓟閻旂厧绀堢憸蹇曟暜濞戙垺鐓冮梺鍨儐椤ュ牓鏌＄仦鐐鐎规洜鍘ч埞鎴﹀炊閳哄﹥楔闂傚倷娴囧銊х矆娴ｈ　鍋撳顐㈠祮妤犵偛鍟伴幑鍕偘閳╁喚娼旀繝纰樻閸ㄧ敻宕戦幇鏉跨闁革富鍘剧壕?
            if message.strip():
                # 婵犵數濮烽弫鎼佸磻閻樿绠垫い蹇撴缁€濠囨煃瑜滈崜姘辨崲濞戞瑥绶為悗锝庡亞椤︿即鎮楀▓鍨珮闁稿锕ㄥΛ鐔封攽閳╁啫鍔ら柛搴ｎ棁_str婵犵數濮烽弫鍛婃叏娴兼潙鍨傞柣鎾崇岸閺嬫牗绻涢幋鐐茬劰闁稿鎸搁～婵嬫偂鎼淬垻褰庢俊銈囧Х閸嬫盯宕婊勫床婵犻潧顑呴悙濠勬喐韫囨稒鍋傞柟杈鹃檮閳锋垹绱掔€ｎ厽纭剁紒鐘崇叀閺屻劑寮村Ο铏逛患闂佷紮绲块崗姗€骞冮埡鍐╁珰闁圭粯甯為悰鈺備繆閻愵亜鈧牠骞愭ィ鍐ㄧ獥閹兼番鍔岀粈鍫ユ煟閵忕姵鍟為柍閿嬪浮閺屾稓浠﹂崜褎鍣紓浣哄У濞碱摨code闂傚倸鍊峰ù鍥敋瑜忛埀顒佺▓閺呮繄鍒掑▎鎾崇婵＄偛鐨烽崑鎾诲礃椤斿ジ鍞堕梺闈涱檧婵″洭宕㈡禒瀣拺闂傚牊渚楅悞楣冩煕鎼淬劋鎲炬い銏℃椤㈡棃宕卞▎鎴床濠电姰鍨煎▔娑㈡嚐椤栫偛鍌ㄩ悗娑欙供濞?                safe_message = safe_str(message.strip())
                loop = asyncio.get_running_loop()
                loop.create_task(self.connection_manager.send_log_message({
                    "type": "console",
                    "level": "ERROR" if self.stream_type == "stderr" else "INFO",
                    "message": safe_message,
                    "timestamp": loop.time(),
                    "source": self.stream_type
                }))
        except Exception:
            # 婵犵數濮烽弫鍛婃叏閻戝鈧倹绂掔€ｎ亞鍔﹀銈嗗坊閸嬫捇鏌涢悢閿嬪仴闁糕斁鍋撳銈嗗坊閸嬫挾绱撳鍜冭含妤犵偛鍟灒閻犲洩灏欑粣鐐烘⒑瑜版帒浜伴柛鎾寸洴钘濋柕濞垮劗閺€浠嬫煟閹邦剙绾фい銉︾矌缁辨帞绱掑Ο鍝勵潓濡炪倖娲╃紞浣哥暦濡警鍟呮い鏃€鍎抽弫鎼佹⒒娴ｇ瓔鍤冮柛銊ㄩ哺缁旂喖宕卞▎鎺懶￠梺绉嗗嫷娈曢柛瀣у墲缁绘盯宕卞Ο鍏煎櫘闂佷紮绲块弫濠氬蓟閳╁啯濯撮柛婵勫剾閵忋倖鐓熼柨婵嗘缁犵偟鈧娲橀敃銏′繆閹间焦鏅滈悹鍥у级濞呮姊婚崒娆愮グ妞ゆ泦鍛床闁归偊鍠楀畷鏌ユ煙鏉堝墽鐣遍柛銊ュ€块弻锝夊閻樺啿鏆堥梺绋块缁夊綊寮诲☉銏犵婵°倐鍋撻悗姘煎墴閹灚瀵肩€涙ǚ鎷洪梺鍛婄箓鐎氼厼顔忓┑鍡忔斀妞ゆ梻鍋撻弳顒傗偓瑙勬礀閹碱偊鍩ユ径濠庢僵閺夊牃鏅槐鍐测攽閻愯埖褰х紒鑼舵硶濞戠敻宕奸弴鐐殿唶闂佸憡鍔﹂崰妤呮偂?
            pass
    
    def flush(self):
        self.original_stream.flush()

# WebSocket闂傚倸鍊风粈渚€骞栭位鍥敃閿曗偓閻ょ偓绻濋棃娑卞剰缁炬儳顭烽弻锝夊箛椤掑倷绮甸梺鍝勬缁捇骞冨Δ鍛棃婵炴垶鐟﹂崰鎰箾閹寸偞灏紒澶婄秺瀵濡搁妷銏☆潔濠碘槅鍨拃锔界妤ｅ啯鈷?
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.logging_enabled = False
        self.original_stdout = None
        self.original_stderr = None

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        
        # 婵犵數濮烽弫鍛婃叏閻戝鈧倹绂掔€ｎ亞鍔﹀銈嗗坊閸嬫捇鏌涢悢閿嬪仴闁糕斁鍋撳銈嗗坊閸嬫挾绱撳鍜冭含妤犵偛鍟灒閻犲洩灏欑粣鐐烘⒑瑜版帒浜伴柛鎾寸懃椤曪絽鐣￠幍铏杸闂佺粯鍔栧娆撴倶閿曞倹鐓欓柛娑橈攻鐏忥妇鈧娲橀崹鍧楃嵁濮椻偓瀵剟濡烽敂缁樼秾闂傚倷娴囬～澶愬磿閾忣偅娅犻幖鎼厛閺佸﹪鏌￠崶銉ョ仾闁抽攱鍨块幃宄扳枎韫囨搩浠归梺鐓庡娴滎亪寮诲☉娆愬劅闁靛牆鎳庨幆鐐测攽閳ュ啿绾ч柛鏃€娲熼崺鐐哄箣閻橆偄浜鹃柨婵嗙凹濞撮鎮┑瀣拻濞达綀濮ら妴鍐⒒閸曨偆效鐎规洘鍔曢埞鎴﹀幢閳轰焦顓挎俊鐐€栧ú宥夊磻閹炬枼鏀介柨娑樺閸樻潙鈹戦敍鍕効妞わ箑鐡ㄩ妵鍕棘鐠恒剱褎鎱ㄦ繝鍕笡闁瑰嘲鎳橀幃鐑藉箥椤斾勘鍋＄紓鍌氬€风粈渚€藝娴兼潙绠伴柟鎯版缁犳牠鏌ｉ幇闈涘幍闁稿鎳橀弻娑㈠箛閳轰礁顫呴悶?
        if len(self.active_connections) == 1 and not self.logging_enabled:
            self.enable_logging_redirect()

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        
        # 婵犵數濮烽弫鍛婃叏閻戝鈧倹绂掔€ｎ亞鍔﹀銈嗗坊閸嬫捇鏌涢悢閿嬪仴闁糕斁鍋撳銈嗗坊閸嬫挾绱撳鍜冭含妤犵偛鍟灒閻犲洩灏欑粣鐐寸節閻㈤潧浠ч柛瀣崌閹繝濮€閵堝棌鎷洪梺鍝勫€堕崕鎻掆枍閸涘瓨鐓曢柣鏇氱閻忥絿绱掗纰辩吋妤犵偞甯掕灃闁逞屽墰閻ヮ亣顦归柡灞界Ч瀹曨偊宕熼锝嗩唲濠电偛顕刊瀵哥不閹捐绠栧ù鐘差儛閺佸秵鎱ㄥΟ鍧楀摵闁硅尪鍋愮槐鎾存媴缁嬪簱鍋撻崫銉х煋闁荤喐澹嗛弳锕傛⒑椤掆偓缁嬩線寮崶顒佺厽婵☆垱妞块崯蹇斾繆閺屻儺妫戠紒杈ㄦ崌瀹曟帒鈻庨幋顓熜滈梻浣侯焾閿曪箓宕楀鈧獮濠偽旈崨顓㈠敹闂佸搫娲ㄩ崑鐐烘倵椤掑嫭鈷戦梻鍫熺〒婢ф洘銇勯敂璇茬仯闁绘碍鍎抽鍏煎緞鐎ｎ剙甯惧┑鐘灱濞夋盯鎮ч崱娑樼闁靛牆娲ㄧ壕濂告煟濡灝鐨洪柛鈺嬬稻閹便劍绻濋崘鈹夸虎濡ょ姷鍋為幑鍥嵁閹烘妫樻繝闈涘閻忔煡鏌″畝瀣М闁轰焦鍔栧鍕暆閳ь剟寮抽锔藉€?
        if len(self.active_connections) == 0 and self.logging_enabled:
            self.disable_logging_redirect()

    def enable_logging_redirect(self):
        """Docstring."""
        if not self.logging_enabled:
            self.original_stdout = sys.stdout
            self.original_stderr = sys.stderr
            
            # 闂傚倸鍊搁崐鎼佸磹閻戣姤鍊块柨鏇氶檷娴滃綊鏌涢幇鍏哥敖闁活厽鎹囬弻鐔虹磼閵忕姵鐏嶉梺绋款儌閺呮稖鐏冮梺鎸庣箓閹冲酣寮冲▎鎾村仭婵炲棙鐟ч悾鐢告煛瀹€鈧崰鎾诲焵椤掑倹鏆╂い顓炵墛缁傛帟顦归柡灞剧洴婵℃悂濡烽敐鍛垝闂備礁鎼張顒勬儎椤栫偟宓侀悗锝庝簴閺€浠嬫煕閵夈劌鐓愰柨娑樻噽缁辨捇宕掑▎鎴犵崲濡炪們鍊曢崐鍨暦閿濆绀冮柕濞у嫭顔曟繝鐢靛仜濡瑩骞愰崨濠傤嚤闁绘绮悡鏇㈡煛閸ャ儱濡煎褜鍠楅妵鍕疀閿濆懐浠稿┑顔硷功缁垶骞忛崨瀛樺仭闂侇叏绠戝▓婵嬫⒒娴ｈ棄鍚归柛鐘叉瀹曟繈骞嬪┑鎰闂佸壊鍋呭ú鏍煁閸ヮ剚鐓熼柡鍐ㄥ亞閻掑墽鐥弶璺ㄐф慨?
            sys.stdout = WebSocketStreamHandler(self, "stdout")
            sys.stderr = WebSocketStreamHandler(self, "stderr")
            
            self.logging_enabled = True
            print("Log message")

    def disable_logging_redirect(self):
        """Docstring."""
        if self.logging_enabled and self.original_stdout and self.original_stderr:
            sys.stdout = self.original_stdout
            sys.stderr = self.original_stderr
            self.logging_enabled = False
            print("Log message")

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast(self, message: str):
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                # 婵犵數濮烽弫鍛婃叏閻戝鈧倹绂掔€ｎ亞鍔﹀銈嗗坊閸嬫捇鏌涢悢閿嬪仴闁糕斁鍋撳銈嗗坊閸嬫挾绱撳鍜冭含妤犵偛鍟灒閻犲洩灏欑粣鐐烘煟鎼搭垳绉甸柛瀣€搁～婵嬫晝閸屾稈鎷虹紓鍌欑劍閿氬┑顔肩墛缁绘盯宕楅懖鈺傚櫗閻庡灚婢樼€氼剟顢樻總绋跨倞闁挎繂鎳嶆竟鏇㈡⒑闂堚晛鐦滈柛娆忛叄閹偤宕滆閸嬫挸鈻撻崹顔界亪闂佺粯鐗滈崢褔顢氶敐鍡欑瘈婵﹩鍓涢崐鐐烘偡濠婂嫮鐭掔€规洜鏁诲鎾閿涘嫬甯楅柣鐔哥矋缁挸鐣峰鍫熷亜闁绘挸瀛╅悗顒勬倵楠炲灝鍔氭繛璇х到閳讳粙顢旈崼鐔哄幈闂佸湱鍋撻〃鍛村疮閻楀牆顕遍柛銉墯閳锋垿鏌ゆ慨鎰偓鏇炵毈缂傚倷娴囬崺鏍х暆閹间礁违闁稿瞼鍋為弲婊堟煟閹伴潧澧い蹇旀倐濮婅櫣绱掑Ο娲绘⒖濠电偛鎷戠紞渚€骞嗗畝鍕闁哄倶鍎查弬鈧梻浣虹帛閿氱痪缁㈠弮閵嗗倿寮婚妷锔惧幗?
                disconnected.append(connection)

        # 缂傚倸鍊搁崐鎼佸磹妞嬪海鐭嗗〒姘ｅ亾閽樻繃銇勯弽顐汗闁逞屽墾缁犳垿鎮鹃敓鐘茬闁惧浚鍋嗛埀顒佹そ閺岀喖宕楅懖鈺傛闂佸憡鏌ㄩ懟顖濈亱濠碘槅鍨甸崑鎰婵傜绾ч柛顐ｇ☉婵″ジ鏌ｈ箛鏃€灏﹂柡宀€鍠栭、娑橆潩椤掍焦顔掗柣搴ゎ潐濞叉粓宕伴弽顓溾偓浣糕枎閹惧磭顦悷婊勭矒瀹曨垱鎯旈妸锔规嫽?
        for conn in disconnected:
            self.disconnect(conn)

    async def broadcast_json(self, message: dict):
        """Docstring."""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                # 婵犵數濮烽弫鍛婃叏閻戝鈧倹绂掔€ｎ亞鍔﹀銈嗗坊閸嬫捇鏌涢悢閿嬪仴闁糕斁鍋撳銈嗗坊閸嬫挾绱撳鍜冭含妤犵偛鍟灒閻犲洩灏欑粣鐐烘煟鎼搭垳绉甸柛瀣€搁～婵嬫晝閸屾稈鎷虹紓鍌欑劍閿氬┑顔肩墛缁绘盯宕楅懖鈺傚櫗閻庡灚婢樼€氼剟顢樻總绋跨倞闁挎繂鎳嶆竟鏇㈡⒑闂堚晛鐦滈柛娆忛叄閹偤宕滆閸嬫挸鈻撻崹顔界亪闂佺粯鐗滈崢褔顢氶敐鍡欑瘈婵﹩鍓涢崐鐐烘偡濠婂嫮鐭掔€规洜鏁诲鎾閿涘嫬甯楅柣鐔哥矋缁挸鐣峰鍫熷亜闁绘挸瀛╅悗顒勬倵楠炲灝鍔氭繛璇х到閳讳粙顢旈崼鐔哄幈闂佸湱鍋撻〃鍛村疮閻楀牆顕遍柛銉墯閳锋垿鏌ゆ慨鎰偓鏇炵毈缂傚倷娴囬崺鏍х暆閹间礁违闁稿瞼鍋為弲婊堟煟閹伴潧澧い蹇旀倐濮婅櫣绱掑Ο娲绘⒖濠电偛鎷戠紞渚€骞嗗畝鍕闁哄倶鍎查弬鈧梻浣虹帛閿氱痪缁㈠弮閵嗗倿寮婚妷锔惧幗?
                disconnected.append(connection)

        # 缂傚倸鍊搁崐鎼佸磹妞嬪海鐭嗗〒姘ｅ亾閽樻繃銇勯弽顐汗闁逞屽墾缁犳垿鎮鹃敓鐘茬闁惧浚鍋嗛埀顒佹そ閺岀喖宕楅懖鈺傛闂佸憡鏌ㄩ懟顖濈亱濠碘槅鍨甸崑鎰婵傜绾ч柛顐ｇ☉婵″ジ鏌ｈ箛鏃€灏﹂柡宀€鍠栭、娑橆潩椤掍焦顔掗柣搴ゎ潐濞叉粓宕伴弽顓溾偓浣糕枎閹惧磭顦悷婊勭矒瀹曨垱鎯旈妸锔规嫽?
        for conn in disconnected:
            self.disconnect(conn)

    async def send_progress_update(self, progress_data: dict):
        """Docstring."""
        message = json.dumps(progress_data)
        await self.broadcast(message)
    
    async def send_log_message(self, log_data: dict):
        """Docstring."""
        message = json.dumps(log_data)
        await self.broadcast(message)

manager = ConnectionManager()

# 闂傚倸鍊峰ù鍥х暦閸偅鍙忕€规洖娲ㄩ惌鍡椕归敐鍫綈婵炲懐濮撮湁闁绘ê妯婇崕鎰版煕鐎ｅ吀閭柡灞剧洴閸╁嫰宕橀浣诡潔缂傚倷璁查崑鎾绘煕瀹€鈧崑鐐烘偂韫囨挴鏀介柣鎰版涧娴滅偓绻涢崨顓燁棡濞ｅ洤锕ら—鍐偂鎼粹槅娼庨梻浣告惈閻绱炴担閫涚箚闁归棿绀佸敮闂侀潧顦介崰鏇㈡儉椤忓懐绡€缁剧増蓱椤﹪鏌涚€Ｑ冧壕闂備礁鎼幊鎰板磻閻斿搫鍨濋悹鍥ㄧゴ濡插牊淇婇娑氱煁婵☆偄鍟悾鐑藉Ω閳哄﹥鏅ｉ梺缁樺姇婢у酣濡剁€靛摜纾?
def setup_comprehensive_logging():
    """Docstring."""
    # 闂傚倸鍊峰ù鍥х暦閸偅鍙忕€规洖娲ㄩ惌鍡椕归敐鍫綈婵炲懐濮撮湁闁绘ê妯婇崕鎰版煕鐎ｅ吀閭柡灞剧洴閸╁嫰宕橀浣诡潔闂備礁鎲￠崝蹇涘磻閹剧粯鈷戦柤濮愬€曢弸鎴︽煟閻旀潙鍔ら柍褜鍓氶崙褰掑矗閸愵喖鏋佺€广儱妫楃欢鐐烘煙闁箑鏋涚憸鏉垮濮婃椽骞栭悙鎻掑Ф闂佺粯鎸搁悧鍡涘煝閹炬枼鏋庨柟鐐綑娴狀厼鈹戦悩璇у伐闁瑰啿閰ｉ妴鍌炲礂閼测晝顔曢梺鍛婄懃椤﹁鲸鏅堕鍫熺厓?
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    
    # 濠电姷鏁告慨鐑藉极閹间礁纾婚柣鎰惈缁犱即鏌熼梻瀵割槮缂佺姷濮垫穱濠囶敍濠靛嫧鍋撻埀顒勬煛鐎ｎ亞效妤犵偞鐗曡彁妞ゆ巻鍋撳┑鈥茬矙閺屾稓鈧綆鍋嗙粻鐐烘煛瀹€瀣埌閾绘牠鏌嶈閸撶喖骞冭缁绘繈宕熼婵堢憹闂備礁婀遍崕銈夈€冮崱娑欏亗闁绘柨鍚嬮悡蹇撯攽閻愯尙浠㈤柛鏃€纰嶉妵鍕疀婵犲啯鐝氬┑顔硷攻濡炰粙骞婇敓鐘参ч柛娑卞墰閹规洘绻濈喊妯活潑闁稿鎳橀妴鍐川閺夋垹鍘?
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    log_dir = Path(__file__).resolve().parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    # 闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁嶉崟顒佹濠德板€曢崯浼存儗濞嗘挻鐓欓悗鐢殿焾鍟哥紒鎯у綖缁瑩寮婚悢璁胯櫣绱掑Ο鐓庢锭bSocket婵犵數濮烽弫鍛婃叏娴兼潙鍨傞柣鎾崇岸閺嬫牗绻涢幋鐐茬劰闁稿鎸搁～婵嬫偂鎼淬垻褰庢俊銈囧Х閸嬫盯宕婊勫床婵犻潧顑呴悙濠勬喐閺傝?    ws_handler = WebSocketLogHandler(manager)
    ws_handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    detailed_formatter = logging.Formatter(
        '%(asctime)s - %(process)d - %(threadName)s - %(name)s - %(levelname)s - %(message)s'
    )
    ws_handler.setFormatter(formatter)
    
    # 闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁嶉崟顒佹濠德板€曢崯浼存儗濞嗘挻鐓欓悗鐢殿焾鍟哥紒鎯у綖缁瑩寮婚悢鐓庣闁逛即娼у▓顓犵磽娴ｅ搫孝缁剧虎鍙冮獮澶岀矙濞嗘儳鎮戞繝銏ｆ硾閿曘儱危椤掆偓閳规垶骞婇柛濠冩礋楠炲﹥鎯旈妸锕€鍓瑰┑掳鍊曢幊蹇涙偂濞戞﹩鐔嗛悹铏瑰皑閺€濠氭煕鐎ｃ劌鍔﹂柡宀€鍠栭、娆撴嚃閳轰胶鍘介柣搴ゎ潐濞叉牕鐣烽鍐簷濠电偠鎻徊浠嬪箹椤愩倗绀婇柡鍐ㄧ墛閳锋帒霉閿濆洦鍤€妞ゆ洘绮庣槐鎺斺偓锝庡亜閻忔挳鏌熼銊ユ搐瀹告繃銇勯弽銊р槈閹兼潙锕ら埞鎴︻敊缁涘鍔搁梺绯曟櫆閻楃姴鐣烽幋锕€鐓涢柛灞剧矌椤旀洟姊虹化鏇炲⒉闁挎艾鈹戦鍏兼悙闂囧鏌ｅΟ纰卞姕闁兼澘娼￠弻锛勪沪閸撗勫垱濡ょ姷鍋炵敮鈥愁嚕閹绢喗鍋勯柟顓熷坊閸嬫捇骞囬悧鍫濅画濠电姴锕ょ€氼厾娆㈤弻銉︾厽閹烘娊宕濆畝鍕ㄢ偓锕傚炊椤忓棛鏉稿┑鐐村灦椤洭顢欓幒妤佲拺闁告稑锕ゆ慨鍥┾偓娈垮枛閻栧ジ骞嗘笟鈧顕€宕奸悢鍙夊?    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    # 闂傚倸鍊峰ù鍥х暦閸偅鍙忕€规洖娲ㄩ惌鍡椕归敐鍫綈婵炲懐濮撮湁闁绘ê妯婇崕鎰版煕鐎ｅ吀閭柡灞剧洴閸╁嫰宕橀鍛珮缂備焦鍎宠ぐ鐐靛垝濞嗘挸钃熼柍銉﹀墯閸氬骞栫划鍏夊亾閼碱剚鏅奸梻鍌欑劍閹爼宕濆畝鍕柈闁秆勵殔閻撯€愁熆閼搁潧濮囩紒鐘侯嚙铻為柣妤€鐗忕粻鎾寸箾閸喆鈧€?8婵犵數濮烽弫鎼佸磻濞戙埄鏁嬫い鎾跺枑閸欏繐霉閸忓吋缍戠痪鎯ф健閺岋紕浠︾拠鎻掑闂佸搫顑勯悞锕傚Φ閸曨垰鍗虫俊銈傚亾濞存粍鍎宠灃闁绘﹢娼ф禒锕傛煕閺冣偓閻楃娀鐛箛娑樺窛闁哄鍨崇槐鍫曟⒑閸涘﹥绀€闁诲繑宀歌棢婵犲﹤瀚弧鈧梺姹囧灲濞佳勭濠婂牊鐓熸俊銈傚亾婵☆偅绻堝顐﹀礃椤斿槈褍顭跨捄渚剰濞寸娀浜堕幃宄邦煥閸愵亞顔婇梺?
    if hasattr(console_handler, 'stream') and hasattr(console_handler.stream, 'reconfigure'):
        try:
            console_handler.stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass  # 婵犵數濮烽弫鍛婃叏閻戝鈧倹绂掔€ｎ亞鍔﹀銈嗗坊閸嬫捇鏌涢悢閿嬪仴闁糕斁鍋撳銈嗗坊閸嬫挾绱撳鍜冭含妤犵偛鍟灒閻犲洩灏欑粣鐐烘⒑瑜版帒浜伴柛姗€绠栧畷銏ゅ箳濡や礁鈧灚顨ラ悙鑼虎闁告梹纰嶆穱濠囶敃閿濆洦鍣伴梺璇″櫙缁绘繈宕洪埀顒併亜閹烘垵顏柍閿嬪笒闇夐柨婵嗙墱濞兼劗绱掗幆鏉跨毢缂佽鲸甯楀鍕節閸曨偆鍘介梻浣筋嚃閸犳牕顭囬垾宕囨殾闁告鍊ｉ悢鍏兼優闁革富鍘惧畵渚€姊绘担鍛婃儓妞わ富鍨堕幃褍顭ㄩ崼婵堬紱婵犮垼娉涚€垫帡寮跺ú顏呪拻闁稿本鐟ч崝宥夋倵缁楁稑鎳愰惌娆撴煙鏉堥箖妾柛搴㈡煥閳规垿宕掑搴ｅ姼缂備胶濯寸徊浠嬧€旈崘顏佸亾閿濆簼绨奸柟鐧哥悼閻ヮ亪宕滆鐢爼鏌嶇憴鍕伌闁诡喗鐟╁畷锝嗗緞婵犲啰浜烽梻鍌欐祰椤曟牠宕伴弴鐘插灊婵炲棙鍔掔换鍡涙煙闂傚顦﹂柣鎾寸洴閺屾盯骞囬埡浣割瀷濡炪倖鍔曢妶绋款潖濞差亝鍤掗柕鍫濇啗閿熺姵鈷掗柛鏇ㄥ亞鏁堥悗瑙勬礃閸旀洝鐏冮梺鍛婂姀閺呪晛顭囬悢濂夋富闁靛牆鎳愮粻浼存煟濡も偓閿曨亜鐣?
    # 闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁嶉崟顒佹濠德板€曢崯浼存儗濞嗘挻鐓欓悗鐢殿焾鍟哥紒鎯у綖缁瑩寮婚悢鐓庣闁逛即娼у▓顓炩攽閳藉棗浜濋柨鏇樺灲瀵鈽夐姀鐘栥劍銇勯弽顐沪妞ゅ骸绉撮—鍐Χ閸℃顫堢紓渚囧枟閻熲晛顕ｆ繝姘櫢闁绘灏欓ˇ銊╂⒑閹稿孩纾甸柛瀣崌閺屾盯寮埀顒€顫濋妸褎顫曢柟鐑樻⒒绾惧吋淇婇婊冨姦闁瑰嘲缍婇幃妤呭垂椤愶絿鍑￠柣搴㈢濠㈡﹢鎮鹃悜鑺ュ亜缁炬媽椴搁弲锝夋⒑缂佹ɑ鐓ラ柣銊︾箞瀹曟垿骞樼紒妯衡偓鐑芥煟閹寸儐鐒介柛姗€浜跺娲箰鎼达絿鐣靛┑鐐茬湴閸旀垿骞冩导缁般劑鍩″娓抏nd.log 闂傚倸鍊峰ù鍥х暦閸偅鍙忛柟鎯板Г閸婂潡鏌ㄩ弴妤€浜惧銈庡幖閻忔繆鐏掗梺鍏肩ゴ閺呮繈藝椤栫偞鍊垫鐐茬仢閸旀碍绻涢懠顒€鈻堢€规洘鍨块獮妯肩磼濡桨鐢婚梻浣虹帛椤ㄥ懘鎮ф繝鍥х闂侇剙绉甸埛鎴︽煕濠靛棗顏柨娑欐⒒缁辨帡宕ｆ径濠傚Б濡炪値鍘煎ú锔炬崲濠靛棭娼╂い鎺戝€婚弶鍛婁繆閻愵亜鈧牠鎮у鍫濈；婵炴垶姘ㄧ亸鐢碘偓骞垮劚椤︿即鎮¤箛鎿冪唵閻犻缚娅ｆ晶鏇㈡煕閺傝鈧妲愰幒妤佸亹闁肩⒈鍓欓悡鐔兼⒑閸濆嫯顫﹂柛鏂跨焸閸┿儲寰勬繛銏㈠枛瀹曟宕楃喊鍗炴櫖rror.log 闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁撻悩鍐蹭画闂侀潧艌閺呮稒顢婇梻浣告贡婢ф顭垮鈧畷锟犲箮閼恒儳鍘棅顐㈡搐閿曘倖鏅堕崣澶岀闁告侗鍠楀畷宀勬煛瀹€瀣М闁诡喒鏅犲畷锝嗗緞婵犲孩袩闂?traceback
    backend_file_handler = RotatingFileHandler(
        log_dir / "backend.log",
        maxBytes=20 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    backend_file_handler.setLevel(logging.DEBUG)
    backend_file_handler.setFormatter(detailed_formatter)

    error_file_handler = RotatingFileHandler(
        log_dir / "error.log",
        maxBytes=20 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    error_file_handler.setLevel(logging.ERROR)
    error_file_handler.setFormatter(detailed_formatter)
    
    # 濠电姷鏁告慨鐑藉极閹间礁纾块柟瀵稿Х缁€濠囨煃瑜滈崜姘跺Φ閸曨垰鍗抽柛鈩冾殔椤忣亪鏌涘▎蹇曠闁哄矉缍侀獮鍥敇閻旇櫣鈻忕紓鍌欑婢у酣宕戦妶澶婅摕婵炴垯鍨归崡鎶芥煏婵炲灝鍔氱紒鐘虫そ濮婅櫣绮欓崠鈥冲闂佺顑冮崐婵嗩嚕鐠囨祴妲堥柕蹇婂墲濞呮粓姊洪崨濠傚闁告柨鐭傞垾鏍醇閵夛腹鎷虹紓渚囧灡濞叉ê鈻嶉崨瀛樼厽妞ゆ挾鍋涢埀顒佹倐椤㈡岸鏁愭径瀣患闁诲繒鍋為崕鎶藉几閸岀偞鈷戦柛娑橈攻婢跺嫰鏌涢幘鍗炲婵″弶鍔曢～婵嬫嚋濞堟寧顥婃俊鐐€栭崝鎴﹀垂閻戞ê绶為柛鏇ㄥ厵娴滄粓鏌曟繛鍨姶婵″弶妞介弻鐔煎矗婢跺鈧劙鏌熼銊ユ搐闁卞洭鏌ｉ弬鎹愵劅婵″樊鍓氱换?
    root_logger.addHandler(ws_handler)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(backend_file_handler)
    root_logger.addHandler(error_file_handler)

    # 濠电姷鏁告慨鐑藉极閹间礁纾块柟瀵稿Х缁€濠囨煃瑜滈崜姘跺Φ閸曨垰鍗抽柛鈩冾殔椤忣亪鏌涘▎蹇曠闁哄矉缍侀獮鍥敋閸涱喗鐦滈梻浣侯焾椤戝棝骞戦崶顒€绠栭柣鎴ｅГ閻掍粙鏌ㄩ弬鍨缓闁挎洖鍊归埛鎴︽煕濞戞﹫鍔熼柟鍐插暟缁辨帞绱掑Ο蹇ｄ邯椤㈡岸鏁愭径妯绘櫔闂侀€炲苯澧ǎ鍥э躬閹粓鎸婃竟鈹垮妿閹叉瓕绠涘☉杈ㄦ櫓閻庡箍鍎遍ˇ浼存偂濞戞﹩鐔嗛悹铏瑰劋椤ョ偞绻涢崨顓熷櫤缂佺粯绋撻幏鐘侯槾闁伙絽鐏氶〃銉╂倷閺屻儱寮版繝寰枫倕鐓愮€垫澘瀚换婵嬪炊椤帞鑸归梻鍌氬€风欢姘焽瑜旈垾锕傚醇閵夈儳锛熼梻渚囧墮缁夌敻宕戦崒鐐寸厱鐎光偓閳ь剟宕戦悙鐑樺亗婵炴垶鍩冮崑鎾荤嵁閸喖濮庡┑鐐存綑閸婂灝顕ｉ妸锕€顕遍悗娑櫭禒顓炩攽閻樿宸ラ柟鍐查叄閵嗗倿宕楅懖鈺冾啎闂佸憡鐟ラˇ杈ㄦ櫠椤忓牊鐓?
    safe_filter = SafeLogFilter()
    root_logger.addFilter(safe_filter)
    for handler in root_logger.handlers:
        handler.addFilter(safe_filter)
    
    # 闂傚倸鍊峰ù鍥х暦閸偅鍙忕€规洖娲ㄩ惌鍡椕归敐鍫綈婵炲懐濮撮湁闁绘ê妯婇崕鎰版煕鐎ｅ吀閭柡灞剧洴閸╁嫰宕橀浣割潓闂備胶顭堥鍛搭敄婢舵劕钃熼柨婵嗩槹閸嬪嫮绱掔€ｎ偒鍎ユ俊顐㈡濮婃椽宕崟顒夋￥婵犫拃鍕垫畷缂佸矁椴哥换婵嬪炊閼稿灚娅栨繝纰夌磿閸嬬娀顢氳缁傚秵銈ｉ崘鈺冨弰闂婎偄娴勭徊鑺ョ濠婂厾褰掓偐閾忣偄鍞夊┑顔硷工閹碱偅鏅ラ梺鎼炲劀閸愬墽鈧娊姊虹拠鎻掝劉闁告垵缍婂畷銏ゆ嚌閹殿喕缃曢梻鍌欑閸熷潡骞栭銈傚亾濮樼厧娅嶉柟顔兼健閸┾偓妞ゆ巻鍋撻柍瑙勫灦楠炲﹪鏌涙繝鍐╃鐎规洦鍨堕獮姗€顢欓挊澶夌钵闂備胶鎳撴晶鐣屽垝椤栫偞鍋?
    logging.getLogger('hyperrag').setLevel(logging.INFO)
    logging.getLogger('openai').setLevel(logging.INFO)
    logging.getLogger('httpx').setLevel(logging.WARNING)  # 闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁撻悩鎻掔€梺姹囧灩閻忔艾鐣烽弻銉︾厵闁规鍠栭。濂告煕鎼达紕效闁哄矉缍佹俊鍫曞幢濮楀棙娓怲P闂傚倸鍊峰ù鍥х暦閸偅鍙忛柡澶嬪殮濞差亶鏁囬柕蹇曞Х閸濇姊绘笟鍥у缂佸鏁诲畷鏇㈠箣濠㈡繂缍婂畷妤呭礂閼测晝鈻忕紓鍌欑贰閸嬪嫮绮旇ぐ鎺戣摕闁哄洨鍠庣欢鐐烘煕椤愶絿绠撳┑顔哄灮缁?
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    
    # 缂傚倸鍊搁崐鐑芥嚄閸洘鎯為幖娣妼閸屻劑鏌涢幘妤€鎳嶇粭澶岀磽娴ｆ垝鍚璺烘疆erRAG闂傚倸鍊搁崐鐑芥嚄閸洖纾块柣銏㈩焾閻ょ偓绻濋棃娑卞剬闁逞屽墾缁犳挸鐣锋總绋课ㄩ柕澹懎骞€闂佽崵鍠愮划宥呂涢崘顔惧祦闁糕剝绋戠粈鍐┿亜閺冨洤浜规い锔芥緲椤啴濡堕崱妤€娼戦梺绋款儐閹稿濡甸崟顖涙櫜闁糕剝鐟ュ銊╂⒑閸濆嫮鐒跨紒缁樼箓閻ｇ兘鎮℃惔妯绘杸闂佸綊鍋婇崢婊堟晝閸屾稈鎷洪梺缁樺灍閺呮稒鏅堕弻銉︾厽闁绘梹娼欓崝銉╂煟韫囨柨娴慨濠冩そ閹瑩鎸婃径濠傂撴繝鐢靛仜閹冲繐煤閻旈鏆﹂柟杈剧畱鍞梺鍐叉惈閸婄敻骞忛崫鍕垫富闁靛牆妫欓悡銉╂煟閵娧冨幋鐎规洘鍨块獮妯肩磼濡桨绨婚柣搴ｆ嚀鐎氼厼顭垮Ο鑲╀笉闁挎繂顦伴埛鎴︽煕濠靛棗顏存俊鍙夋倐閺岋絽螖閳ь剟鏁冮鍫㈠祦闁圭増婢樼粻鐟懊归敐鍥剁劸闁诡垳鍋涢—鍐Χ閸℃ê钄奸梺鎼炲妼濠€閬嶆偖閹屽悑濠㈣泛顑囬崢顏呯節閵忥絾纭鹃柣妤€妫濆畷婵嬪Χ閸モ晝锛?
    hyperrag_modules = [
        'hyperrag.base',
        'hyperrag.hyperrag',
        'hyperrag.llm',
        'hyperrag.operate',
        'hyperrag.prompt',
        'hyperrag.storage',
        'hyperrag.utils'
    ]

    for module_name in hyperrag_modules:
        module_logger = logging.getLogger(module_name)
        module_logger.setLevel(logging.INFO)
        # 缂傚倸鍊搁崐鐑芥嚄閸洘鎯為幖娣妼閸屻劑鏌涢幘妤€鎳嶇粭澶愭⒑閸忛棿鑸柛搴㈠閹广垽宕卞Ο闀愮盎闂佸搫绉查崝濠冪濠婂牊鐓曢悗锝庡亝瀹曞矂鏌熼悡搴ｇШ妞ゃ垺娲熼敐鐐侯敇閻旂硶鏋欓梻鍌氬€搁崐椋庣矆娓氣偓楠炴牠顢曢敃鈧悿顕€鏌曟繛鐐珔缁炬儳娼″鍫曞醇濮橆厽鐝曢悗瑙勬礃閻擄繝寮婚敓鐘茬闁挎繂鎳嶆竟鏇犵磽閸屾瑧顦︽い鎴濇嚇閺佸啴顢旈崼婵堢暫闂侀潧绻堥崐鏇犵矆閸緷褰掓晲閸噥浠╅悗瑙勬礉濞夋盯鍩為幋锔藉€锋繛鍫熷椤ユ捇姊虹粙娆惧剱闁告梹鐗犻獮鍫ュΩ閳哄倸浠虹紓浣割儓濞夋洟顢欓崶顒佲拻濞撴艾娲ゆ晶顔剧磼婢跺鍤熺紒顔肩墦瀹曞崬鈽夊▎鎴濆箺婵犲痉鏉库偓鎰板磻閹剧粯鐓熸俊銈傚亾缂佺粯鍨圭划鈺呮偄妞嬪孩娈曢梺鍛婃处閸撴瑦绂掗娑氱閺夊牆澧界粔顒併亜椤愩埄妲烘繛鍡愬灲閹崇娀顢楅崒婊愮闯闁诲骸绠嶉崕閬嶅箠閹邦厽娅忛梺?
        module_logger.propagate = True
        # 濠电姷鏁告慨鐑藉极閹间礁纾块柟瀵稿Х缁€濠囨煃瑜滈崜姘跺Φ閸曨垰鍗抽柛鈩冾殔椤忣亪鏌涘▎蹇曠闁哄矉缍侀獮鍥敋閸涱喗鐦滈梻浣侯焾椤戝棝骞戦崶顒€绠栭柣鎴ｅГ閻掍粙鏌ㄩ弬鍨缓闁挎洖鍊归埛鎴︽煕濞戞﹫鍔熼柟鍐插暟缁辨帞绱掑Ο铏逛淮濡炪値鍘煎ú锔炬崲濠靛棭娼╂い鎺戝€搁埀顒傚仱濮婃椽妫冨☉杈╁彋缂備胶濮甸崹濂搞€傛禒瀣拻闁稿本鐟х粣鏃€绻涢懝鏉垮惞鐎垫澘锕ョ换婵嗩潩椤掑偆妲烽柣搴″帨閸嬫捇鏌涢弴銊ヤ簼婵″樊鍓熼弻锝堢疀閺囩偘绮堕悷婊嗗焽閸旀垿鐛幒妤€鍗抽柣妯虹仛濠㈡垿姊洪悷鏉挎倯闁伙綆浜畷婵堜沪鐟欙絾鐏佸┑鐘绘涧濡矂寮ㄦ禒瀣厓闁芥ê顦伴ˉ婊堟煟韫囨梻鎳囬柡灞界Х椤т線鏌涢幘瀵哥畵闁宠绉瑰鎾閻樼绱?
        module_logger.addFilter(safe_filter)

    root_logger.info(f"闂傚倸鍊搁崐椋庣矆娓氣偓楠炴牠顢曢敃鈧悿顕€鏌曟繛鐐珔缁炬儳娼″鍫曞醇濮橆厽鐝曢悗瑙勬礃閻擄繝寮婚敓鐘茬闁靛ě鍐炬毇婵犵妲呴崑鍛存晝閵忋倕钃熸繛鎴欏灩鍞銈嗙墱閸嬬偤顢撳鍜佹富闁靛牆妫楁慨澶愭煛閸滀礁浜伴柛鈹惧亾濡炪倖甯掗崐褰掑吹閳ь剟姊洪崷顓烆嚥闁靛牆鍟╁Ч妤呮⒑閸涘﹤濮﹂柛鐘崇墱缁顫濈捄铏诡啇濠电儑缍嗛崜娆愪繆娴犲鐓? {log_dir / 'backend.log'}")
    root_logger.info(f"闂傚倸鍊搁崐鎼佸磹閻戣姤鍊块柨鏃堟暜閸嬫挾绮☉妯诲闁稿绻濋弻鏇熺箾閻愵剚鐝曢梺缁樻尰閻╊垶寮诲☉銏犵疀闁告挷鑳堕弳鐘绘⒑閸涘﹥鈷愭慨妯稿妿濡叉劙骞掗弮鍌滐紲濠碘槅鍨卞鍨涢崘顔藉€垫繛鍫濈仢濞呮﹢鏌涢幘璺烘瀻闁伙絿鍏樺畷濂稿即閻斿憡鐝曠紓鍌欑劍缁嬫垿顢栭崨顔绢浄婵炲樊浜濋悡鐔煎箹鏉堝墽绋婚柛銈傚亾闂備礁婀辩€典粙濡堕崘褎鐫忛梻浣告啞閸旓箓宕伴弽顐や笉婵娉涚粻瑙勭箾閿濆骸澧┑鈥茬矙閺? {log_dir / 'error.log'}")
    
    return root_logger

def configure_hyperrag_logging():
    """Docstring."""
    try:
        # 婵犵數濮烽弫鍛婃叏閻戝鈧倹绂掔€ｎ亞鍔﹀銈嗗坊閸嬫捇鏌涢悢閿嬪仴闁糕斁鍋撳銈嗗坊閸嬫挾绱撳鍜冭含妤犵偛鍟灒闁煎鍊楅悾浠嬫⒑闂堚晝绋婚柛鈺冨瀬rRAG闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁撻悩鍐蹭画闂佹寧娲栭崐绋啃ч弻銉у彄闁搞儯鍔庨埊鏇㈡煟閹惧崬鍔滅紒缁樼洴楠炲鎮滈崱娆忓Ш闂備胶绮敮妤呭箖閸岀偛钃熸繛鎴烆焸閻旇櫣鐭欓幖瀛樻尭娴滅偓淇婇妶鍛殲妞ゎ偅娲熼弻锟犲礃閵娧冾暫闂佹椿鍘介〃鍛扮亙闂佹寧绻傞幊搴ㄥ汲濞嗘垹纾奸柍褜鍓熷畷姗€顢欓悾灞藉箞婵犵數鍋為崹鍫曟偡閿斿墽绀婇柟杈鹃檮閻撴洟鏌￠崒婵愬殭闁告棑绠撻弻鈥崇暆鐎ｎ剛鐦堥悗瑙勬礃閿曘垽寮崘顔肩劦妞ゆ帒瀚粈澶嬫叏濡じ鍚痪?
        if HYPERRAG_AVAILABLE:
            # 闂傚倸鍊峰ù鍥敋瑜嶉湁闁绘垼妫勯弸渚€鏌熼梻瀵割槮闁稿被鍔庨幉鎼佸棘鐠恒劍娈鹃梺鎸庣箓椤︻垰顪冮悾宀€纾奸柣妯虹湴閳ь剙鐣秗RAG闂傚倸鍊搁崐鐑芥嚄閸洖纾块柣銏㈩焾閻ょ偓绻濋棃娑卞剬闁逞屽墾缁犳挸鐣锋總绋课ㄩ柕澹懎骞€闂佽崵鍠愮划宀€绮旈悜鑺ュ€堕柟鐑橆殕閳锋垿鏌ｉ幇顖涱棄闁告柣鍎茬换娑㈠川椤旂晫顦伴悗瑙勬礃閸ㄦ寧淇婇悜鑺ユ櫆缂備焦锕╅崯宥夋⒒娴ｈ櫣甯涢柛鏃€鐗曢…鍥р枎閹惧磭顦梺鍛婃尫閼冲墎澹曟禒瀣厱閻忕偞宕樻竟姗€鏌￠崱娆忎槐闁哄被鍔岄埥澶婎潨閸℃ǚ鏋呴梻?
            try:
                import hyperrag
                import hyperrag.base
                import hyperrag.storage
                import hyperrag.llm
                import hyperrag.utils
                
                # 婵犵數濮烽弫鎼佸磻閻愬搫鍨傞柛顐ｆ礀缁犳澘螖閿濆懎鏆為柛搴★攻閵囧嫰濡堕崶銊︾伋erRAG闂傚倸鍊搁崐鐑芥倿閿曞倹鍎戠憸鐗堝笒缁€澶屸偓鍏夊亾闁逞屽墴閸┾偓妞ゆ帊绀侀崵顒€霉濠婂懎浠遍柛鈹惧亾濡炪倖甯掔€氼厼鈽夎閺岋綁顢楅埀顒勫Χ閹间胶宓佸鑸靛姈閸嬪鏌涢銈呮瀻妞ゅ孩鎸婚幈銊╁箲椤掆偓鐎氼厾浜搁銈囩＜闁奸晲绲绘竟姗€鏌ｉ敐澶樻缂侇喗鐟ч幏鐘绘倷椤掍緡妫冮悗瑙勬礈閸犳牠銆佸鈧幃鈺冨枈婢跺苯鍨辨繝鐢靛Х椤ｈ棄危閸涙潙纾婚柍褜鍓熼弻锟犲川椤栨矮鎴风紓渚囧枦椤曆囧煡婢跺á鐔奉煥閸曨剦妫冮悗瑙勬礈閸犳牠銆佸▎鎰闁绘鐗忓鏍⒒閸屾瑧顦﹂柟纰卞亜鐓ら柕濞炬櫅绾惧鏌ｉ幇顔煎妺闁?
                modules_to_configure = [
                    hyperrag,
                    hyperrag.base,
                    hyperrag.storage, 
                    hyperrag.llm,
                    hyperrag.utils
                ]
                
                for module in modules_to_configure:
                    if hasattr(module, '__name__'):
                        logger = logging.getLogger(module.__name__)
                        logger.setLevel(logging.INFO)
                        logger.propagate = True
                        # 濠电姷鏁告慨鐑藉极閹间礁纾块柟瀵稿Х缁€濠囨煃瑜滈崜姘跺Φ閸曨垰鍗抽柛鈩冾殔椤忣亪鏌涘▎蹇曠闁哄矉缍侀獮鍥敋閸涱喗鐦滈梻浣侯焾椤戝棝骞戦崶顒€绠栭柣鎴ｅГ閻掍粙鏌ㄩ弬鍨缓闁挎洖鍊归埛鎴︽煕濞戞﹫鍔熼柟鍐插暟缁辨帞绱掑Ο铏逛淮濡炪値鍘煎ú锔炬崲濠靛棭娼╂い鎺戝€搁埀顒傚仱濮婃椽妫冨☉杈╁彋缂備胶濮甸崹濂搞€傛禒瀣拻?
                        safe_filter = SafeLogFilter()
                        logger.addFilter(safe_filter)
                        
                print("[OK] HyperRAG logging configuration completed")

            except ImportError as e:
                print(f"[WARNING] Failed to import HyperRAG module for logging configuration: {safe_str(e)}")

    except Exception as e:
        print(f"[WARNING] HyperRAG logging configuration failed: {safe_str(e)}")

# 闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁嶉崟顒佹濠德板€曢崯顖氱暦閺屻儲鐓曠€光偓閳ь剟宕戦悙鐑樺亗闁哄洢鍨洪悡娑氣偓骞垮劚閸燁偅淇婇崹顕呯唵鐟滄粓宕滃顓犫攳濠电姴娴傞弫鍐煟閺傛寧鍟為柣婵囶殘缁辨挻鎷呴崫鍕戯絿绱掔€ｎ偄鐏遍柣蹇撳暣濮婃椽宕ㄦ繝鍌毿曢梺鍝ュУ閻楃姴鐣烽姀鐘瀻闁瑰濮烽敍?
main_logger = setup_comprehensive_logging()

# 闂傚倸鍊搁崐鎼佸磹閻戣姤鍊块柨鏇楀亾妞ゎ厼鐏濊灒闁兼祴鏅濋悡瀣⒑閸撴彃浜濇繛鍙夛耿瀹曟垿顢旈崼鐔哄幈濠电姴锕ら幊鎰板汲閺€鎱箁RAG闂傚倸鍊搁崐椋庣矆娓氣偓楠炴牠顢曢敃鈧悿顕€鏌曟繛鐐珔缁炬儳娼″鍫曞醇濮橆厽鐝曢悗?
configure_hyperrag_logging()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # 闂傚倸鍊风粈渚€骞栭位鍥敃閿曗偓閻ょ偓绻濇繝鍌滃闁稿绻濋弻宥夊传閸曨剙娅ｉ梻鍌氬亞閸ㄥ爼寮婚敐澶婄闁挎繂妫Λ鍕⒑濞茶骞楁い銊ユ嚇濠€浣糕攽閻樿宸ラ悗姘煎墰缁厼顫濋幍浣镐壕闁割煈鍋呯欢鏌ユ倵濮橆厽绶查柣锝囧厴閹垻鍠婃潏銊︽珝闂備胶绮弻銊╂儍濠靛纾婚柟鍓х帛閸婄兘鏌ｉ幋鐏活亪鍩€椤掆偓閻忔岸銆冮妷鈺傚€烽柤纰卞厸閾忓酣姊虹拠鍙夌濞存粠浜璇测槈閵忕姷鍘搁梺绋挎湰閸ゅ酣鍩€椤掍礁绗х紒杈ㄥ浮椤㈡瑧鎲撮崟顒傚綀闂備線娼уú锕傚礉濞嗗繒鏆﹂柟鐑橆殕閸婄兘鎮楅悽娈跨劸濠殿喖鍢查埞鎴︽倷閼搁潧娑х紓浣瑰絻濞尖€崇暦閺囥垹围濠㈣泛顑呮禒濂告煛婢跺﹦澧戦柛鏂挎捣缁粯銈ｉ崘鈺冨幍闁诲孩绋掗…鍥╃不濡警鐔嗙憸搴ｇ矙閹达附绠?
            await manager.send_personal_message(f"Message received: {data}", websocket)
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# 闂傚倸鍊烽悞锕傛儑瑜版帒鏄ラ柛鏇ㄥ灠閸ㄥ倿鏌ｉ敐鍛伇濞戞挸绉归弻鐔告綇妤ｅ啯顎嶉梺绋款儛娴滎亪寮诲☉銏犲嵆闁靛鍎虫禒鈺冪磽娓氬洤浜滅紒澶婄秺瀵鎮㈢喊杈ㄦ櫖濠电偞鍨堕敃鈺佄涢崱娆戠＝濞达絽鎼瓭濡炪値鍘鹃崗姗€鎮伴鈧浠嬪Ω閿斿墽肖闂備礁鎲￠幐鍡涘川椤旂瓔鍟岄梻鍌氬€风欢姘跺焵椤掑倸浠滈柤娲诲灡閺呭爼顢涘☉娆忓伎濠碘槅鍨抽…鍫熸叏閸岀偞鐓欐い鏇炴缁♀偓闂佽桨鐒﹂幑鍥箖閳哄懎绀冮柟缁樺笒椤ュ姊婚崒娆戭槮闁规祴鈧秮娲晝閸屾氨顦┑顔筋焾閸╂牠宕愰崹顐犱簻闁哄啠鍋撻柛銊︾箘閹广垽宕卞Ο鍦畾闂侀潧鐗嗛幏瀣磿閹达附鐓曢柟鐑樻尭椤ュ绱掓潏銊ョ瑲闁瑰嘲鎳橀幃婊兾熺紒妯兼闂佽姘﹂～澶娒哄鈧妴鍐╃節閸愌呯畾闂佺粯鍨兼慨銈夊疾濠靛鐓冪憸婊堝礈濮橆剦鍤楅柛鏇ㄥ亽閸氬顭跨捄渚剳闁?
@app.post("/files/embed-with-progress")
async def embed_files_with_progress(request: FileEmbedRequest, user: dict = Depends(require_current_user)):
    """
    闂傚倸鍊搁崐椋庣矆娴ｈ櫣绀婂┑鐘插亞閻掔晫鎲歌箛鏇燁潟闁绘劕顕弧鈧梺鎼炲劀閸ヮ煉绱梻鍌欑閹诧紕鎹㈤崒婧惧亾濮樼厧娅嶇€殿喗濞婃俊鑸靛緞鐎ｎ亖鍋撻崼鏇熺厽闁归偊鍨伴悡鎰亜閵夈儺妲洪柍褜鍓氶鏍窗濡や胶绠惧┑鐘叉搐閽冪喖鏌ㄩ悢鍝勑㈢痪鎯у悑閹便劌顫滈崱妤€绠瑰銈忚吂閺呯姴顫忓ú顏咁棃婵炴垶鐟Λ鐐烘⒑缁嬪尅宸ラ柣蹇旂箞閹儳鐣￠柇锔藉兊闂佸吋鎮傚褔宕滈鍕€垫繛鍫濈仢閺嬬喖鏌涘▎蹇嬪仱rRAG闂傚倸鍊搁崐鐑芥倿閿旈敮鍋撶粭娑樻噽閻瑩鏌熸潏楣冩闁搞倖鍔栭妵鍕冀椤愵澀娌梺绋款儍閸斿秹濡甸崟顖氱疀闁宠桨璁查崑鎾诲箛閺夎法锛涢梺瑙勫礃椤曆囧箲閼哥偣浜滈柟鎹愭硾娴犳帗绻涘畝濠佺盎闁宠鍨块弫宥夊礋椤愶紕鎹曢梻浣侯焾閿曪箓骞婇幘鐑┾偓锕傚炊閳哄倸鐝板┑鐐存綑椤戝棝锝炲鍛斀闁宠棄妫楅悘鐔兼偣閳ь剟鏁冮崒姘冲煘濠电偛妯婃禍婵嬪煕閹烘垯鈧帒顫濋浣规倷婵炲瓨绮嶇换鍐箞閵娿儙鐔虹矙閸噮娼庨梻?

    闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁撻悩鍐蹭画闂侀潧顦弲娑氬閸︻厽鍠愰柣妤€鐗嗙粭鎺撴叏?
        file_ids: 闂傚倸鍊搁崐椋庣矆娓氣偓楠炴牠顢曢敃鈧壕鍦磼鐎ｎ偓绱╂繛宸簼閺呮煡鏌涘☉鍙樼凹闁诲氦顕ч—鍐Χ閸愩劎浼勯梺鍝勵儏缁夌懓顫忕紒妯诲闁告稑锕ら弳鍫ユ煟閵忊晛鐏℃い銊ワ躬婵℃挳宕橀埡浣虹獮闂佸綊鍋婇崕?
        chunk_size: 闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁嶉崟顒佹闂佸湱鍎ら崵锕€鈽夊Ο婊勬閸┾偓妞ゆ帒瀚ч埀顒婄畵瀹曞爼顢楅埀顒勬倿濞差亝鐓曢柟鎵虫櫅婵¤法绱掗幇顔间槐闁诡喖鍢查…銊╁礃椤庮垎鍥ㄧ厵?
        chunk_overlap: 闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁嶉崟顒佹闂佸湱鍎ら崵锕€鈽夊Ο婊勬閸┾偓妞ゆ帒瀚ч埀顒婄畵瀹曞爼顢楁担瑙勵仧闂備胶绮敋缁剧虎鍙冨畷銏ゅ箳濡や礁鈧灚顨ラ悙鑼虎闁告梹宀搁弻鐔煎礃閸欏宕崇紓?
        rag_system: RAG缂傚倸鍊搁崐鎼佸磹妞嬪孩顐介柨鐔哄Т閸ㄥ倿姊婚崼鐔恒€掗柡鍡畵閺岋綁濮€閵堝棙閿梺?(hyperrag/cograg)
        target_database: 闂傚倸鍊搁崐鐑芥嚄閸洖纾块柣銏㈩焾閻ょ偓绻濋棃娑卞剰闁搞劌鍊搁埞鎴﹀磼濮橆厼鏆堥梺缁樻尰缁嬫垿婀侀梺鎸庣箓閹冲繘骞嗛崼鐔翠簻闁挎繂鐗嗘禍褰掓煃瑜滈崜婵嬶綖婢舵劕绠伴柣鎴ｅГ閸婂潡鏌ㄩ弴鐐测偓鍝ョ不濮樿埖鐓涢柛鎰╁妿婢ф洜绱掗悩宸吋闁哄睙鍡欑杸闁挎繂鎳嶇花濠氭⒑闁偛鑻晶顔剧棯缂併垹骞樻俊鍙夊姍楠炴帡骞樺畷鍥╃嵁濠电姷鏁告慨鎾磹婵犳碍鍎庨幖杈剧悼绾捐棄霉閿濆嫮鐭欓柛婵囨そ閺岋綁鎮㈤崣澶嬬彅闂佷紮绲块崗姗€寮幇顓炵窞濠电姴瀚慨锔戒繆閻愵亜鈧牕顔忔繝姘；闁圭偓鐣禍婊呮喐婢舵劕纾婚柟鎯у绾捐棄霉閿濆嫮鐭欓柛婵婃閳ь剙鍘滈崑鎾绘煙闂傚顦﹂柡瀣╄兌閳ь剙绠嶉崕鍗灻洪敐鍛煢妞ゅ繐濞婅ぐ鎺撳亹鐎瑰壊鍠栭崜浼存⒑閸涘﹤鐏╁┑顔炬暩閹广垹鈹戦崶鈺冪槇闂佺鏈崙瑙勭婵傚憡鈷戝ù鍏肩懅閻ｈ京绱撳鍜冭含妤犵偛鍟灃闁告劏鏅涢弸鍌炴⒑閸涘﹥澶勯柛鐘崇墵钘熸繝闈涱儐閳锋垿鏌涢幘鐟扮毢闁告ɑ鐩弻娑㈠Ω閵壯冪厽闂佺粯渚楅崰鏍敇閸忕厧绶炲┑鐘插婵附淇婇悙顏勨偓鏍暜閹烘柡鍋撳鐓庡闁逞屽墯閼归箖藝椤栫偐鈧妇鎹勯妸锕€纾繛鎾村嚬閸ㄤ即宕滈柆宥嗏拺閻犲洦褰冮惁銊╂煕閻樻剚娈曠紒宀冮哺缁绘繈宕戦懞銉︹拻闁逞屽墾缂嶅棝宕滃▎鎾虫槬鐎光偓閳ь剛妲愰幘瀛樺闁汇値鍨伴崢锟犳⒑鏉炵増绁版い鏇嗗洦鍋╃€瑰嫭瀚堥弮鍫濆窛妞ゆ挸娲㈤崝鎴﹀蓟閺囩喎绶為柛顐ｇ箓婵垽姊洪崨濞氭垹鏁幒妤€鐓橀柟杈惧瘜閺佸﹪鏌ｉ敐鍛伇缂佸彉鍗冲铏圭矙閸栤剝鏁鹃梺缁橆殘婵挳顢氶敐澶婄闁兼亽鍎辨禍婊堟⒑缂佹ɑ灏繛瀵稿厴椤㈡瑦寰勫畝鈧壕?
        update_file_database: 闂傚倸鍊搁崐椋庣矆娓氣偓楠炴牠顢曢妶鍌氫壕婵鍘у顔锯偓瑙勬礃濞叉鎹㈠┑瀣倞闁靛ě鍐ㄧ闂傚倷鐒﹂幃鍫曞磿濠婂牆宸濇い鏃囨閺嬫盯姊婚崒娆戭槮闁圭⒈鍋婇幊鐔碱敍閻愬瓨娅囧銈呯箰鐎氱兘宕甸弴鐔翠簻闁圭儤鍨甸鈺呮煟閹邦剨韬柡灞诲姂瀵噣宕掑鍕晵闂備胶顭堥鍐礉閹存繍娼栭柧蹇撴贡閻瑩鎮归幁鎺戝妞ゆ柨娲鍝勑ч崶褉鍋撻弴鐏绘椽鏁傞崜褏鐒块梺鍦劋椤ㄥ懘鏌嬮崶顒佺厪濠㈣埖绋撻悾閬嶆煕閹垮啫寮慨濠冩そ瀹曘劍绻濋崘顭戞П闂備礁鎲￠幐濠氭嚌妤ｅ啫鐓濋柟鎹愵嚙闁卞洭鏌￠崶鈺佹灁闁告鏁诲娲閳轰胶妲ｉ梺鍛娒肩划娆撳箚?
    """
    if not HYPERRAG_AVAILABLE:
        raise HTTPException(status_code=500, detail="HyperRAG is not available")

    # 婵犵數濮烽弫鍛婃叏閻戝鈧倹绂掔€ｎ亞鍔﹀銈嗗坊閸嬫捇鏌涢悢閿嬪仴闁糕斁鍋撳銈嗗坊閸嬫挾绱撳鍜冭含妤犵偛鍟灒閻犲洩灏欑粣鐐烘⒑瑜版帒浜伴柛鎾寸洴椤㈡瑩宕堕浣叉嫼闂佺鍋愰崑娑㈠礉閳ь剟姊洪崨濠佺繁闁哥姵顨婇幆渚€鎮欏ù瀣杸闂佺粯鍔樼亸娆撳箺閻樼數纾兼い鏃囧亹閻掑摜鈧鍠撻崝鎴﹀箚閸岀偞鍎岄柣鐐甸ケme闂傚倸鍊搁崐鐑芥倿閿旈敮鍋撶粭娑樻噽閻瑩鏌熺€电浠ч梻鍕閺岋繝宕橀妸銉㈠亾閹间礁鍨傛繝闈涱儐閻撶喖鏌￠崶銉ュ闁哄棗绻樺濠氬磼濮橆兘鍋撻悜鑺ュ€块柨鏇楀亾妞ゎ厼鐏濊灒闁兼祴鏅濋悡瀣⒑閸撴彃浜濇繛鍙夛耿瀹曟垿顢旈崼鐔哄幈闂佹枼鏅涢崰姘舵倿娴犲鐓冪紓浣股戦ˉ鍫熸叏婵犲啯銇濈€规洏鍔嶇换婵嬪礋椤掆偓濞呮姊绘担铏瑰笡妞ゃ劌鐗婇幈銊╂倻閽樺顦梺鍦劋椤ㄥ繘寮鍡欑瘈濠电姴鍊搁鈺傘亜鎼淬垻娲存慨濠冩そ濡啫鈽夊顒夋毇闂備胶鎳撻崯鎸庮殽濮濆瞼浜辨繝娈垮枟閵囨盯宕戦幘缁樼厸?
    if request.kb_name:
        kb = await kb_manager.get_kb(request.kb_name, owner_user_id=user.get("id"), include_legacy=True)
        if kb:
            if not request.target_database:
                request.target_database = kb["database_name"]
            request.rag_system = kb.get("rag_system", request.rag_system)
            request.chunk_size = kb.get("chunk_size", request.chunk_size)
            request.chunk_overlap = kb.get("chunk_overlap", request.chunk_overlap)
            request.update_file_database = True
            # 闂傚倸鍊峰ù鍥х暦閸偅鍙忕€规洖娲ㄩ惌鍡椕归敐鍫綈婵炲懐濮撮湁闁绘ê妯婇崕鎰版煕鐎ｅ吀閭柡灞剧洴閸╁嫰宕橀崹顔煎絾缂傚倷鐒﹂崬鑽ょ礊娓氣偓瀵鈽夐姀鐘靛姶闂佸憡鍔楅崑鎾绘偩婵傚憡鈷?- 闂傚倸鍊搁崐鐑芥嚄閸洖纾块柣銏㈩焾閻ょ偓绻涢幋娆忕仾闁稿鍊濋弻鏇熺箾瑜嶇€氼厼鈻撴导瀛樷拺闁革富鍙€濡炬悂鏌涢悩宕囧⒌鐎规洩绻濋獮搴ㄦ嚍閵夈儮鍋撻崹顐ょ闁瑰鍎愭导鍡涙煙鏉堥箖妾柛瀣€块弻宥堫檨闁告挾鍠栧濠氭晲婢跺浜归柡澶婄墐閺呪晛危椤旂晫绡€闁冲皝鍋撻柛灞剧矌閻撴捇姊虹拠鈥虫灈婵炲皷鈧磭鏆﹂柛妤冨亹濡插牊淇婇娑欍仧婵☆偆鍠栧缁樻媴鐟欏嫬浠╅梺绋块椤嘲顫忔禒瀣妞ゆ牭绲鹃弲婵嬫⒑閼恒儍顏埶囬鈶斤綁宕奸妷锔惧幍闂佽鍨庣仦鑺ヮ啀闂?domain
            try:
                if os.path.exists(SETTINGS_FILE):
                    with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                        _settings = json.load(f)
                else:
                    _settings = {}
                _settings["hyperrag_domain"] = kb.get("domain", "default")
                with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(_settings, f, ensure_ascii=False, indent=2)
            except Exception as e:
                main_logger.warning("Log message")

    # 缂傚倸鍊搁崐鎼佸磹閻戣姤鍊块柨鏇炲€搁拑鐔兼煏婵炵偓娅撻柡浣稿閺屾稑鈽夐崡鐐茬闂佸搫妫庨崐婵嬪蓟濞戙垹鐒洪柛蹇婃櫆閸ㄥ墎绮嬪澶娢у璺侯儑閸樻悂姊虹粙鎸庢拱缂佸鍨块、姘煥閸涱垳锛滈梺閫炲苯澧撮柛鈹惧亾濡炪倖甯婇懗鍓佸姬閳ь剟姊洪棃娑㈢崪缂佹彃澧藉☉鍨偅閸愨晛鈧灚鎱ㄥΟ鐓庡付婵炲懎绉甸〃銉╂倷閹绘帗娈茬紓浣虹帛缁诲牆鐣烽幒妤€围闁告侗鍣崥娆撴⒒閸屾瑧绐旈柍褜鍓涢崑娑㈡嚐椤栨稒娅犳い鏍仦閻撴瑥銆掑顒備虎濠碘€虫健閺屽秷顧侀柛鎾卞妿缁辩偤宕卞☉妯碱槶濠殿喗顭堥崺鏍磻閳哄懏鈷戞い鎺嗗亾缂佸鏁婚幃锟犲即閻旇櫣鐦堥梻鍌氱墛缁嬫帡藟閻樼鍋撳☉娆戠畼缂?
    if request.kb_name and not request.target_database:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    if request.target_database:
        request.target_database = require_database_access(request.target_database, user)

    total_files = len(request.file_ids)
    consume_document_quota_if_needed(user, total_files)

    # 闂傚倸鍊峰ù鍥х暦閸偅鍙忛柟鎯板Г閸婂潡鏌ㄩ弴妤€浜惧銈庡幖閻忔繆鐏掗梺鍏肩ゴ閺呮繈藝椤栫偞鍊垫鐐茬仢閸旀碍銇勯敂鍨祮鐎规洘娲橀幆鏃堝Ω閿旀儳骞楅梻浣告惈缁夊爼寮崫銉х煋妞ゆ棃鏁崑鎾斥枔閸喗鐝梺绋款儏閿曨亪鐛崘顓ф▌閻庤娲滈崢褔鍩為幋锕€閱囨繛鎴灻奸崰濠囨⒒閸屾瑧顦︽繝鈧柆宥呭偍鐟滄棃骞冨ú顏勎╅柍杞拌兌椤斿洭姊绘担鍝ヤ虎妞ゆ垵娲崺鐐差吋閸涱亝鏂€闂佺粯锚瀵爼骞栭幇顔剧＜?    if request.target_database:

    try:
        await preflight_hyperrag_api_services()
    except Exception as e:
        detailed_error = log_detailed_exception(
            main_logger,
            "Embedding API test failed",
            e,
            {
                "file_ids": request.file_ids,
                "rag_system": request.rag_system,
                "target_database": request.target_database,
                "chunk_size": request.chunk_size,
                "chunk_overlap": request.chunk_overlap,
                "runtime_settings": get_runtime_settings_context(),
            },
        )
        user_friendly_error = extract_user_friendly_error(detailed_error)
        await manager.send_progress_update({
            "type": "error",
            "error": user_friendly_error,
            "detailed_error": detailed_error[:500],
            "total_files": total_files,
        })
        raise HTTPException(status_code=400, detail=user_friendly_error)
    
    # 闂傚倷娴囬褏鈧稈鏅犻、娆撳冀椤撶偟鐛ラ梺鍝勭▉閸樿偐澹曡ぐ鎺撶厽闁绘梻鍘ф禍浼存煟閺傛寧顥㈤柟顔肩秺瀹曨偊宕熼浣稿壍婵＄偑鍊曞ù姘跺磻婵犲洤钃熼柣鏃傗拡閺佸﹦鐥鐘崇効闁告凹鍋婇幃妤€鈻撻崹顔界彯闂佸憡鎸鹃崰搴ㄦ偩閻戣棄閱囬柡鍥╁枑濞呭棛绱撴担鍦槈妞ゆ垵鎳忕粋鎺懨洪鍛幗闁瑰吋鐣崐銈咁焽閹扮増鐓欓柛娑橈攻閸婃劙鏌熷畷鍥ф灈妞ゃ垺鐩幃娆撴嚑椤掑倸骞€?
    asyncio.create_task(process_files_with_progress(request, total_files, user.get("id")))
    
    return {
        "message": "Operation failed",
        "total_files": total_files,
        "processing": True
    }

async def process_files_with_progress(request: FileEmbedRequest, total_files: int, owner_user_id: str | None = None):
    """Docstring."""
    try:
        print(f"="*60)
        print("Log message")
        print("Log message")
        print("Log message")
        print(f"="*60)
        
        successful_files = 0
        failed_files = 0
        
        for i, file_id in enumerate(request.file_ids):
            file_info = None
            database_name = None
            content = None
            try:
                print(f"\n{'='*40}")
                print("Log message")
                print("Log message")
                print(f"{'='*40}")
                
                # 闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁撻悩鍐蹭画闂佹寧娲栭崐鎼佸垂閸岀偞鐓曠憸搴ㄣ€冮崨瀛樺€块柛顭戝亖娴滄粓鏌熺€电浠滄い鏇熺矌缁辨帗鎷呴悷閭︽缂備浇椴哥敮鐐垫閹烘嚦鐔煎即閻旈浼屽Δ鐘靛仜濡繂顕ｉ鈧畷濂告偄閸涘﹦褰嗛梻鍌欑閸氬绂嶆禒瀣？闁规儼妫勭粈鍕归悩宸剱闁?
                await manager.send_progress_update({
                    "type": "progress",
                    "file_id": file_id,
                    "current": i + 1,
                    "total": total_files,
                    "percentage": ((i + 1) / total_files) * 100,
                    "status": "processing",
                    "message": "Operation completed"
                })
                
                # 闂傚倸鍊搁崐椋庣矆娓氣偓楠炴牠顢曢埛姘そ婵¤埖寰勭€ｎ亙妲愰梻渚€娼ц墝闁哄懏鐩幏鎴︽偄鐏忎焦鏂€闂佺粯锚瀵爼骞栭幇顓濈箚妞ゆ劧缍囬懓鍧楁煛鐏炲墽娲村┑锛勫厴椤㈡盯鎮欓幖顓涘亾瀹ュ拋娓婚柕鍫濇婵啰绱掗鐣屾噰鐎殿喖顭烽弫鎰板川閸屾粌鏋涚€规洖缍婇、娆撳箚瑜嶇紓姘舵⒒閸屾瑧绐旈柍褜鍓涢崑娑㈡嚐椤栫偛鍌ㄩ柛娑橈梗缁诲棝鏌ｉ幇顓熺稇缂佹う鍥ㄧ厵鐎瑰嫭澹嗙粔娲煙椤斿搫鐏紒顔界懅閹瑰嫰濡歌瀹撲線姊婚崒娆戭槮闁规祴鈧秮娲晝閸屾艾鍋嶆繛瀵稿Т椤戝懐澹曡ぐ鎺撶厽闁归偊鍘鹃妶瀛樹繆?
                print("Log message")
                file_manager.update_file_status(file_id, "processing")
                
                # 闂傚倸鍊搁崐椋庣矆娓氣偓瀹曘儳鈧綆鍠栫壕鍧楁煙閹増顥夐幖鏉戯躬閺屻倝鎳濋幍顔肩墯婵炲瓨绮岀紞濠囧蓟濞戙垹唯妞ゆ梻鍘ч～鈺佲攽閳藉棗浜濋柨鏇樺灲瀵鈽夐姀鐘栥劍銇勯弽顐沪妞ゅ骸绉撮—鍐Χ閸℃顫戝┑鈽嗗亜鐎氼垵銇愭笟鈧娲箹閻愭彃濮风紓浣藉蔼婵倝寮查崼鏇炵闁?
                print("Log message")
                main_logger.info("Log message")
                file_info = file_manager.get_file_by_id(file_id, owner_user_id=owner_user_id, include_legacy=True)
                if not file_info:
                    error_msg = "Operation failed"
                    print("Log message")
                    main_logger.error(error_msg)
                    await manager.send_progress_update({
                        "type": "error",
                        "file_id": file_id,
                        "filename": getattr(file, "filename", "unknown"),
                        "current": i + 1,
                        "total": total_files
                    })
                    failed_files += 1
                    continue
                
                print("Log message")
                print("Log message")
                print("Log message")
                print("Log message")

                # 婵犵數濮烽弫鎼佸磻閻樿绠垫い蹇撴缁€濠囨煃瑜滈崜姘辨崲濞戞瑥绶為悗锝庡亞椤︿即鎮楀▓鍨珮闁稿锕ユ穱濠囨嚋闂堟稓绐為柣搴秵娴滄粍绔熼崱娑欌拻濞达綀娅ｇ敮娑㈡煟濡ゅ﹤骞樼紒杈╁仦閹峰懘宕滈幓鎺擃吙婵＄偑鍊栭崝褔姊介崟顖氱；閻庯綆鍠楅悡鏇熴亜閹板墎鎮肩紒鐘筹耿閺屾洟宕奸鍌滄殼闂佸搫鐬奸崰鏍箖閳╁啯鍎熼柨婵嗘閸犳牠姊绘担鍛婅础闁冲嘲鐗撳畷鎴﹀幢濡烆澁缍侀獮鍥敄閼恒儳鈧姊鸿ぐ鎺戜喊濞存粎鍋熺划璇差潩閼哥鎷虹紓浣割儐鐎笛冿耿閹殿喚纾奸悗锝庡亝鐏忔壆绱掗崒姘毙фい銏＄洴閹瑧鈧數顭堥獮宥囩磽閸屾瑧顦︽い鎴濇閳ь剛鐟抽崶褏顔愰梺瑙勫婢ф鎮￠悢鍏肩叆婵犻潧妫Σ娲煟閿濆棙銇濋柡灞稿墲閹峰懘宕妷鎰剁悼閳ь剙鐏氬妯尖偓姘煎櫍閸┾偓妞ゆ帒锕︾粔闈浢瑰鍛沪缂佸倹甯￠獮鍥偋閸碍瀚奸梻浣告啞缁诲倻鈧凹鍓熼崺鈧い鎺戝亞閻掗箖鎮￠妶澶嬬叆婵犻潧妫欓崳鎶芥煛鐎ｎ亪鍙勯柡灞炬礉缁犳稒绻濋崘銊︾彴闂備胶顭堥鍡涘箲閸ヮ剙绠栧ù鐘差儏閸ㄥ倹銇勯幇鈺佺仾闁伙綆鍓涚槐鎾诲磼濞嗘挻顎栭梺鍛婃煥缁夊綊骞冮敓鐘虫櫢闁绘灏欓悾楣冩⒑閸涘﹤濮﹂柛鐘崇墱缁牏鈧綆鍋佹禍婊堟煙閸濆嫮肖闁告柨绉甸妵鍕棘鐠恒剱褎鎱ㄦ繝鍐┿仢闁诡喚鍏橀幃褔宕奸敐鍥舵敤濠电姵顔栭崰妤勫綘闂佸憡姊归崹鍨嚕?
                if request.target_database:
                    database_name = file_manager.sanitize_database_name(request.target_database)
                    # 闂傚倸鍊搁崐椋庣矆娓氣偓楠炴牠顢曢埛姘そ婵¤埖寰勭€ｎ亙妲愰梻渚€娼ц墝闁哄懏鐩幏鎴︽偄鐏忎焦鏂€闂佺粯锚瀵爼骞栭幇顓濈箚妞ゆ劧缍囬懓鍧楁煛鐏炲墽娲村┑锛勫厴椤㈡盯鎮欓幖顓涘亾瀹ュ拋娓婚柕鍫濇婵啰绱掗鐣屾噰鐎殿喛顕ч埥澶婎煥閸涱垱婢戦梻浣筋潐瀹曟﹢宕洪弽顓熷€垫い鏃傛櫕缁犻箖鎮楅悽娈跨劸鐎涙繈姊虹紒姗嗘畷闁圭懓娲悰顕€宕卞☉妯碱槰濡炪倖妫侀崑鎰八囬弶娆炬富闁靛牆妫楃粭鍌炴煟閹虹偟鐣垫い銏＄懃椤撳吋寰勭€Ｑ勫闂備浇宕甸崰鎾存櫠濡ゅ啯瀚婚柍鈺佸暞閸?
                    if request.update_file_database:
                        file_manager.update_file_database(file_id, database_name)
                        print("Log message")
                else:
                    database_name = file_info["database_name"]
                print("Log message")
                
                main_logger.info("Log message")
                
                # 婵犵數濮烽弫鎼佸磻閻愬搫鍨傞柛顐ｆ礀缁犳澘螖閿濆懎鏆欑痪鎯ф健閺屾洟宕煎┑鎰ч梺绋块閿曨亪寮诲澶婄厸濞达絽鎲″▓鍫曟⒑瀹曞洨甯涙俊顐㈠暣瀵鏁嶉崟銊ヤ壕闁挎繂绨肩花濠氭煛閸℃瑥浠х紒杈ㄥ浮瀹曟帒鈽夊Ο纰卞剬闂備礁婀遍幊鎾垛偓姘緲閻ｇ兘顢曢敃鈧粈瀣亜閹惧绠栨俊顖氾攻缁绘繈鎮介棃娴讹絾銇勯弮鈧悧鐘茬暦娴兼潙鍐€妞ゆ挆鍕珗闂備礁鎲℃笟妤呭垂椤忓牆纾婚柟鎯х摠婵挳鏌涢幇鈺佸婵絻鍨藉娲焻閻愯尪瀚板褌鍗抽弻鈩冩媴鐟欏嫬鈧劖顨ラ悙璇ц含妤犵偞锕㈤獮鍡涘级閸熷喛绻濆娲传閸曨噮娼堕梺绋垮閻撯€崇暦閺囩儐鍚嬪璺侯儑閸橀亶姊虹憴鍕剹闁告ü绮欓、鏃堛€呴弶鍓匯AG闂傚倸鍊峰ù鍥敋瑜庨〃銉х矙閸柭も偓鍧楁⒑椤掆偓缁夊澹曠紒妯圭箚妞ゆ牗鑹鹃幃鎴炪亜?
                # 闂傚倸鍊搁崐椋庣矆娓氣偓楠炴牠顢曢妶鍥╃厠闂佺粯鍨堕弸鑽ょ礊閺嵮岀唵閻犺櫣灏ㄩ崝鐔兼煛閸℃劕鈧洟婀侀梺鎸庣箓濞层倝宕濈€ｎ喗鍊垫慨姗嗗幖閸濈儤鎱ㄦ繝鍐┿仢鐎规洖缍婇、姘跺川椤撶偛顥愬┑鐘垫暩婵參宕戦幘缁樼厵缂備降鍨归弸鐔兼煃闁垮鐏﹂柕鍥у楠炲洭鍩℃担鍝勫Ф婵犵鍓濊ぐ鍐礊婵犲洤绠栨俊銈傚亾妞ゎ偅绻堥弫鎰板川椤忓懎鐦盇G缂傚倸鍊搁崐鎼佸磹妞嬪孩顐介柨鐔哄Т閸ㄥ倿姊婚崼鐔恒€掗柡鍡畵閺岋綁濮€閵堝棙閿梺?
                if request.rag_system == "cograg":
                    if not COGRAG_AVAILABLE:
                        return {"success": False, "message": "Cog-RAG is not available"}
                    print("Log message")
                    main_logger.info("Log message")
                    rag = get_or_create_cograg(database_name)
                    print("Log message")
                    main_logger.info("Log message")
                else:
                    if not HYPERRAG_AVAILABLE:
                        return {"success": False, "message": "HyperRAG is not available"}
                    print("Log message")
                    main_logger.info("Log message")
                    rag = get_or_create_hyperrag(
                        database_name,
                        chunk_size=request.chunk_size,
                        chunk_overlap=request.chunk_overlap,
                    )
                    print("Log message")
                    main_logger.info("Log message")
                
                # 闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁撻悩鍐蹭画闂佹寧娲栭崐鎼佸垂閸岀偞鐓曠憸搴ㄣ€冮崨瀛樺€块柛顭戝亖娴滄粓鏌熺€电浠滄い鏇熺矌缁辨帗鎷呴悷閭︽缂備浇椴搁幑鍥х暦閹烘垟鏋庨柟鎼幗琚﹀┑鐘殿暯濡插懘宕戦崨顖氬灊閹兼番鍔岀粻鏌ユ煏韫囨洖顫嶉柣鏃囨绾惧吋淇婇姘儓濠碘剝濞婂缁樻媴閻熼偊鍤嬮梺鍝勮閸旀垶淇婇棃娴崇喖宕楅悡搴＄哎闂備胶纭堕崜婵堢矙閹烘鍋?
                await manager.send_progress_update({
                    "type": "file_processing",
                    "file_id": file_id,
                    "filename": file_info["filename"],
                    "database_name": database_name,
                    "stage": "reading",
                    "message": "Operation completed",
                    "rag_system": request.rag_system  # 濠电姷鏁告慨鐑藉极閹间礁纾块柟瀵稿Х缁€濠囨煃瑜滈崜姘跺Φ閸曨垰鍗抽柛鈩冾殔椤忣亪鏌涘▎蹇曠闁哄矉缍侀獮鍥偋閸喖鏁梺璇查閻忔岸鎮￠敓鐘茶摕闁靛牆妫欓崣蹇涙煙闁箑鍘撮柛瀣尭铻栭柛娑卞幗濡差剟姊虹紒姗嗙劷缂侇噮鍨堕幃鈥斥槈濮橈絽浜炬鐐茬仢閸旀岸鏌熼崘鑼缂侇喗宀稿畷绋课旀担鍝勫箺?
                })
                
                # 闂傚倸鍊峰ù鍥х暦閸偅鍙忛柡澶嬪殮濞差亜鐓涢柛婊€鐒﹂弲顏堟偡濠婂嫬鐏村┑锛勬暬楠炲洭寮剁捄銊モ偓鐐差渻閵堝棗鍧婇柛瀣尰娣囧﹪顢曢敐蹇氣偓鍧楁煛鐏炲墽娲村┑锛勫厴椤㈡盯鎮欓幖顓涘亾瀹ュ拋娓婚柕鍫濇婵啰绱掗鐣屾噰鐎殿喛顕ч埥澶愬閻樼數鏉告俊鐐€栫敮濠勭矆娴ｇ硶鏋?
                print("Log message")
                main_logger.info("Log message")
                content = await file_manager.read_file_content(file_info["file_path"])
                print("Log message")
                main_logger.info("Log message")
                
                # 闂傚倸鍊搁崐椋庣矆娓氣偓楠炴牠顢曢妶鍌氫壕婵鍘ф晶顖炴煛閸涙澘鐓愮紒鍌涘笧閳ь剨缍嗛埀顒夊弿闂勫嫰骞堥妸銉庣喖骞愭惔锝冣偓鎰磽娴ｆ彃浜鹃梺鍛婂姦閸犳鎮￠弴鐔虹闁瑰瓨绻傞懜瑙勵殽閻愭惌娈滈柡灞诲妼閳藉鈻庤箛鎿冩綒闁?
                preview = content[:200] + "..." if len(content) > 200 else content
                print("Log message")
                
                # 闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁撻悩鍐蹭画闂佹寧娲栭崐鎼佸垂閸岀偞鐓曠憸搴ㄣ€冮崨瀛樺€块柛顭戝亖娴滄粓鏌熸潏鍓хɑ缁绢叀鍩栭妵鍕晜閻撳寒娲紓浣介哺鐢骞忛崨瀛樺€绘俊顖滅帛閻︽捇鏌ｆ惔銈庢綈婵炲弶锕㈤妴鍐╃節閸愌呯畾闂佺粯鍨煎Λ鍕偂濞戙垺鐓曢悘鐐佃檸濞堟洟鏌ｆ惔銈夊摵缂佺粯绻堥幃浠嬫濞戞鎹曢梻浣虹帛椤ㄥ懐鎹㈠Ο渚殨妞ゆ劑鍊楅惌娆撳箹鐎涙ɑ灏伴柣蹇庣窔濮婃椽鎮烽柇锕€娈堕梺绋款儑閸嬬偟绮嬪澶娢ч柛鈩冪懅椤旀洟姊洪悷閭﹀殶濞村吋绻堥、鏃堝醇椤愶絾娅?
                await manager.send_progress_update({
                    "type": "file_processing",
                    "file_id": file_id,
                    "filename": file_info["filename"],
                    "database_name": database_name,
                    "stage": "embedding",
                    "message": "Operation completed"
                })
                
                # 闂傚倸鍊搁崐椋庣矆娴ｉ潻鑰块弶鍫氭櫅閸ㄦ繃銇勯弽銊х煁闁哄棙绮撻弻鐔兼倻濮楀棙鐣堕梺娲诲幗椤ㄥ﹪寮诲☉銏犵労闁告劦浜栧Σ鍫㈢磽娴ｆ彃浜鹃梺绯曞墲缁嬫帡鎮￠悢鐑樺枑鐎广儱娲﹂～鏇犵棯椤撶偛鍔歳RAG
                print("Log message")
                print("Log message")
                main_logger.info("Log message")
                main_logger.info("Log message")

                # 闂傚倸鍊风粈渚€骞栭位鍥敃閿曗偓閻ょ偓绻濇繝鍌滃闁稿绻濋弻宥夊传閸曨剙娅ｉ梻鍌氬亞閸ㄨ泛顫忓ú顏勫瀭妞ゆ洖鎳庨崜鏉款渻閵堝棙绀夊瀛樻倐楠炲牓濡搁妷搴ｅ枔閹风姴顔忛鏂ょ磼闂傚倷绀侀幖顐⒚洪姀銈呭瀭鐟滅増甯楅崕妤佷繆閵堝懏鍣洪柣鎾寸懇瀵爼宕煎☉妯侯瀴闂佸搫鎳愰幑鈧琫rRAG闂傚倸鍊搁崐鐑芥倿閿曞倹鍎戠憸鐗堝笒缁€澶屸偓鍏夊亾闁逞屽墴閸┾偓妞ゆ帊绀侀崵顒勬煕閵娿儳锛嶆俊鍙夊姍楠炴鈧稒锚椤庢捇姊洪崨濠勨槈妞ゎ収鍓欒灋闁绘劗鍎ら埛鎺懨归敐鍫燁棄闁告艾缍婇弻娑氣偓锝庡亞閳藉鎽堕悙瀵哥瘈濠电姴鍊归崳铏光偓瑙勬礃閻擄繝寮诲☉銏犵疀闁稿繐鎽滈弫鏍⒑?
                try:
                    await rag.ainsert(content)
                    print("Log message")
                    main_logger.info("Log message")
                except Exception as embed_error:
                    error_msg = log_detailed_exception(
                        main_logger,
                        "Embedding API test failed",
                        embed_error,
                        {
                            "file_id": file_id,
                            "filename": file_info.get("filename") if file_info else None,
                            "file_size": file_info.get("file_size") if file_info else None,
                            "file_path": file_info.get("file_path") if file_info else None,
                            "database_name": database_name,
                            "rag_system": request.rag_system,
                            "target_database": request.target_database,
                            "chunk_size": request.chunk_size,
                            "chunk_overlap": request.chunk_overlap,
                            "content_chars": len(content) if content is not None else None,
                            "runtime_settings": get_runtime_settings_context(),
                        },
                    )

                    # 闂傚倸鍊搁崐椋庣矆娴ｉ潻鑰块弶鍫氭櫅閸ㄦ繃銇勯弽顐粶缂佲偓婢舵劖鐓欓柣鎴炆戦埛鎰亜閹邦亞鐭欓柡宀嬬秮婵偓闁靛繆鏅濋崝鎼佹⒑閸涘娈旂痪缁㈠弮閹偓妞ゅ繐鐗嗙粻姘辨喐濠婂牆纾块柟瀵稿Х绾惧ジ寮堕崼娑樺婵炴惌鍠氶埀顒冾潐濞叉牕鐣烽鍕厺閹兼番鍔岀粻娑欍亜閺冨洤袚妞ゆ柨绻樺濠氬磼濮橆兘鍋撻悜鑺ュ€块柨鏃堟暜閸嬫挾绮☉妯诲闁稿绻濋弻鏇熺箾閸喖澹嬮柟鍏肩暘閸斿矂鎮欐繝鍥ㄧ叆婵犻潧妫欓崳褰掓煃瀹勯偊妲圭紒缁樼〒閳ь剛鏁搁…鍫㈡暜閸洘鐓欓柧蹇ｅ€嬮鍫熷仼闁绘垹鐡旈弫鍌炴煕閳╁啯绀冮柛鏇炲暣濮婄儤瀵煎▎鎴濆煂闂佹椿鍓欓崥瀣嚗閸曨垰绀嬫い鏍ㄧ〒閸?                    main_logger.error(f"闂傚倸鍊搁崐椋庣矆娓氣偓楠炴牠顢曢敃鈧壕鍦磼鐎ｎ偓绱╂繛宸簼閺呮繈鏌涚仦缁㈠殼闁靛鏅滈悡鏇㈡倶閻愰潧浜鹃柣銊﹀灴閺岋繝宕遍幇顑藉亾濠靛绠栨慨妞诲亾闁诡喗鐟╅幊婊冣枔閹稿寒妫勯梺璇插椤旀牠宕伴弽顓炵柈闁秆勩仜閳ь剨绠撳畷绋课旈埀顒傜不濮樿埖鐓欐繛鍫濈仢閺嬨倗绱撻崼銉ゆ喚闁哄矉缍侀幃銏ゅ传閵夛箑娈忕紓鍌欒兌婵敻骞戦崶顒佸仒妞ゆ柨妲堥弮鍫濈劦妞ゆ帒鍟版禍? {error_msg}")

                    # 濠电姷鏁告慨鐑姐€傞挊澹╋綁宕ㄩ弶鎴狅紱闂侀€炲苯澧撮柡灞剧〒閳ь剨缍嗛崑鍛暦瀹€鍕厸鐎光偓鐎ｎ剛锛熸繛瀵稿婵″洭骞忛悩璇茬闁圭儤鍩堝娑㈡⒒閸屾瑨鍏岀紒顕呭灦閹囧即閻斿憡鐝烽柟鍏肩暘閸斿瞼绮婚悢鍏煎€垫繛鎴烆伆閹寸偛鍨旈柟缁㈠枟閻撶喖鏌熺€电鍓遍柣鎺嶇矙閺岋繝宕卞▎蹇婃瀰濠殿喖锕︾划顖炲箯閸涘瓨鍋￠梺顓ㄧ畱濞堟繈姊绘担钘夊惞闁哥姴妫濆畷婵囨償閿濆棭娼熼梺鍦劋椤ㄥ繘寮崘顔界厪濠㈣埖锚閺嬫稒绻涢崼顐㈠籍婵﹨娅ｉ幏鐘诲矗婢跺闂梻浣侯焾缁绘垿鏁冮姀銈呯畺濞村吋鎯岄弫瀣煃瑜滈崜鐔肩嵁婵犲偆鐓ラ柛顐ゅ櫏濡啫鈹戦悙鏉戠仸闁煎綊绠栭崺鈧い鎺嶇缁楁氨绱掔紒妯兼创妤犵偞顭囬埀顒勬涧婢瑰﹪寮抽敍鍕＝濞达絽澹婇崕鎰版煕閵娿儲璐℃俊鍙夊姍楠炴鎷犻懠顒夊晪闂備礁鍚嬮幃鍌氼焽瑜旈、?                    suggestion = extract_user_friendly_error(error_msg)

                    # 闂傚倸鍊搁崐鐑芥嚄閸洏鈧焦绻濋崶褎妲梺鍝勭▉閸嬪棝鎯屽▎鎾寸厵閺夊牆澧介悾閬嶆煕濮樻剚娼愰柕鍥у楠炴﹢宕￠悙鍏告偅缂傚倷璁查崑鎾垛偓鍏夊亾闁告洦鍓涢崢鍗炩攽閻愭潙鐏ョ€规洦鍓熼悰顔嘉旈崨顔惧幈闁瑰吋鐣崹鍝勭暦瀹€鍕厵妞ゆ棁鍋愮粔铏光偓瑙勬礉濞夋盯鎮鹃敓鐘崇劷闁挎棁妫勯弸鐘电磽閸屾艾鈧娆㈤敓鐘茬獥闁哄稁鍋呭畷鏌ユ煙娴兼潙浜伴柡浣割儐缁绘盯宕卞Ο鍝勵潎闂佺顑呴敃顏堝蓟濞戞粠妲煎銈冨妼濡繂鐣烽弴鐑嗗悑濠㈣泛顑囬崢閬嶆⒑閸濆嫭鍌ㄩ柛鏂跨焸閹﹢鏁撻悩宕囧幐闂佸憡渚楁禍婵嗏枍婵犲洦鐓?                    raise RuntimeError(f"{error_msg}闂傚倸鍊搁崐椋庢濮橆剦鐒界憸宥堢亱濠德板€曢幊搴ｅ瑜版帗鐓曟繝闈涘閸斻倗鐥崣銉х煓闁哄瞼鍠栭獮鎴﹀箛椤掑倸甯垮┑? {suggestion}") from embed_error
                
                # 闂傚倸鍊搁崐椋庣矆娓氣偓楠炴牠顢曢埛姘そ婵¤埖寰勭€ｎ亙妲愰梻渚€娼ц墝闁哄懏鐩幏鎴︽偄鐏忎焦鏂€闂佺粯锚瀵爼骞栭幇顓濈箚妞ゆ劧缍囬懓鍧楁煛鐏炲墽娲村┑锛勫厴椤㈡盯鎮欓幖顓涘亾瀹ュ拋娓婚柕鍫濇婵啰绱掗鐣屾噰鐎殿喖顭烽弫鎰板川閸屾粌鏋涚€规洖缍婇、娆撳箚瑜嶇紓姘舵⒒閸屾瑧绐旈柍褜鍓涢崑娑㈡嚐椤栫偛鍌ㄩ柛娑橈梗缁诲棝鏌ｉ幇顓熺稇缂佹う鍥ㄧ厵鐎瑰嫭澹嗙粔娲煙椤斿搫鐏紒楦垮Г瀵板嫭绻濋崘鈺冨綃闂傚倸鍊风粈浣革耿鏉堚晛鍨濇い鏍ㄧ矋閺嗘粓鏌ｉ幇顒佹儓閸ユ挳姊哄Ч鍥х仼闁硅绻濋幃?
                file_manager.update_file_status(file_id, "embedded")
                
                # 闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁撻悩鍐蹭画闂佹寧娲栭崐鎼佸垂閸岀偞鐓曠憸搴ㄣ€冮崨瀛樺€块柛顭戝亖娴滄粓鏌熸潏鍓хɑ缁绢厼鐖奸弻娑㈠棘鐠恒剱褔鏌＄仦鍓ф创濠碘剝鎮傞弫鍐焵椤掑嫬浼犻柧蹇撳帨閸嬫挾鎲撮崟顒傤槰缂備浇顕ч悧鎾荤嵁閸愵喖顫呴柍钘夋鏁堥梺鐟板悑閻ｎ亪宕瑰ú顏嶆晩闁告稑鐡ㄩ埛鎺懨归敐鍥у妺闁搞倐鍋撻梻浣割吔閺夊灝顫囬悗瑙勬礃缁诲倽鐏冮梺閫炲苯澧撮柛鈹垮灲楠炴鎷犻懠顒夊悈闂備胶绮崝妤冩崲濠靛棭娼╅柨鏇楀亾闁宠鍨块幃娆撳级閹寸姳妗撻梻浣瑰绾板秹濡甸崟顖氭闁告煭銈呮儓闂備礁鎼惌澶屾崲濠靛棛鏆﹂柟顖炲亰濡查箖姊洪崷顓熸珪濠电偐鍋撻梺?
                await manager.send_progress_update({
                    "type": "file_completed",
                    "file_id": file_id,
                    "filename": file_info["filename"],
                    "database_name": database_name,
                    "status": "completed",
                    "message": "Operation completed"
                })
                
                successful_files += 1
                print("Log message")
                
            except Exception as e:
                # 闂傚倸鍊搁崐椋庣矆娓氣偓楠炴牠顢曢埛姘そ婵¤埖寰勭€ｎ亙妲愰梻渚€娼ц墝闁哄懏鐩幏鎴︽偄鐏忎焦鏂€闂佺粯锚瀵爼骞栭幇顓濈箚妞ゆ劧缍囬懓鍧楁煛鐏炲墽娲村┑锛勫厴椤㈡盯鎮欓幖顓涘亾瀹ュ拋娓婚柕鍫濇婵啰绱掗鐣屾噰鐎殿喖顭烽弫鎰板川閸屾粌鏋涚€规洖缍婇、娆撳箚瑜嶇紓姘舵⒒閸屾瑧绐旈柍褜鍓涢崑娑㈡嚐椤栫偛鍌ㄩ柛娑橈梗缁诲棝鏌ｉ幇顓熺稇缂佹う鍥ㄧ厵鐎瑰嫭澹嗙粔娲煙椤斿搫鐏茬€规洘顨婇幊鏍煛娴ｅ憡杈堟繝?
                error_msg = "Operation failed"
                detailed_error = log_detailed_exception(
                    main_logger,
                    error_msg,
                    e,
                    {
                        "file_id": file_id,
                        "filename": file_info.get("filename") if file_info else None,
                        "file_size": file_info.get("file_size") if file_info else None,
                        "file_path": file_info.get("file_path") if file_info else None,
                        "database_name": database_name,
                        "rag_system": request.rag_system,
                        "target_database": request.target_database,
                        "chunk_size": request.chunk_size,
                        "chunk_overlap": request.chunk_overlap,
                        "content_chars": len(content) if content is not None else None,
                        "runtime_settings": get_runtime_settings_context(),
                    },
                )
                print(f"[ERROR] {error_msg}")
                print("Log message")
                main_logger.error("Log message")

                # 闂傚倸鍊搁崐椋庣矆娴ｉ潻鑰块弶鍫氭櫅閸ㄦ繃銇勯弽顐粶缂佲偓婢舵劖鐓涢柛銈呯埣椤ｏ箑效濡ゅ懏鈷戦柟鑲╁仜閸旀挳鏌涢幘瀵告噮闁逞屽墯閼归箖藝椤栫偐鈧妇鎹勯妸锕€纾梺缁樺灦钃遍柟鐑戒憾濮婃椽宕崟顒夋缂備胶绮敃銏狀嚕婵犳碍鏅插璺好￠埡鍛厪濠㈣泛鐗嗛崝鏉懨归悡搴℃殻婵﹦鍎ゅ顏堝箥椤曞懏袦闂備焦瀵уú鈺冪不閹捐崵宓侀煫鍥ㄧ⊕閸嬫劗鈧娲栧ú鐘诲绩閾忣偆绡€闁汇垽娼у瓭濠电偛鐪伴崐妤冨垝婵犳艾绠抽柡鍐ㄥ€婚敍婊冾渻閵堝棙顥嗘い鏇嗗啰鏆ら柛鈩冪⊕閻撴瑦銇勯弮鍥у惞闁活厽鐟ラ埞鎴﹀焺閸愨晛鈧劙鏌℃担绋挎殻闁糕斁鍋撳銈嗗笒鐎氼參宕?
                user_friendly_error = extract_user_friendly_error(detailed_error)
                file_manager.update_file_status(file_id, "error", user_friendly_error)

                # 闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁撻悩鍐蹭画闂佹寧娲栭崐鎼佸垂閸岀偞鐓曠憸搴ㄣ€冮崨瀛樺€块柛顭戝亖娴滄粓鏌熸潏鍓хɑ缁绢厼澧庣槐鎺楀箛椤撶噥妫冮梺鍝勫閸撴繈骞忛崨瀛橆棃闁宠桨绀侀～鐘绘⒒娴ｅ摜绉烘い銉︽尰閹便劑鎮滈挊澶岊唹闂侀潧绻掓慨鍫ユ偄閾忓湱锛滃┑鈽嗗灠閹碱偅淇婇幎鑺モ拻濞达絿鎳撻婊勪繆椤愶紕鍔嶉柟渚垮姂婵″爼宕堕埡鍌︾础婵＄偑鍊栭悧婊堝磻閻愮儤鍋傛繛鎴欏灪閻撴洟鎮橀悙鏉戠濠㈣顭囩槐鎺楀Ω閵娿儱鎯炵紓浣介哺鐢顭囪箛娑樜╃憸蹇涙偩濞差亝鈷戦柣鐔告緲濡插鏌熼搹顐㈠妤犵偞鍨垮畷鐔碱敍濮ｅ皷鏅犻弻銊╁籍閸ヮ灝鎾淬亜閹惧磭绉烘慨濠勭帛閹峰懐鎲撮崟鈺€鎴锋繝鐢靛仧閸樠冾焽閳ュ磭鏆︽繝闈涙－閸氬顭跨捄鐚存敾婵″樊鍓欓埞鎴︽倷閺夋垹浠ч梺鎼炲妼缂嶅﹪骞嗙仦杞挎棃宕ㄩ灏栧亾閻㈠憡鐓ユ繝闈涙閸戝湱绱掗妸褎鏆柡灞剧〒閳ь剨绲婚崝灞炬叏閸岀偞鐓涚€光偓鐎ｎ剛袦婵犵鍓濋幃鍌涗繆閻戣棄唯妞ゆ棁宕电壕楣冩⒒閸屾瑦绁版俊妞煎妿缁牊绗熼埀顒勫极閸愵喗鏅濋柛灞炬皑椤斿棝姊虹紒妯忣亞澹曢銏犵厴鐎广儱鎳夐弨浠嬫煟濡搫绾ч柟鍏煎姉缁?
                await manager.send_progress_update({
                    "type": "file_error",
                    "file_id": file_id,
                    "filename": getattr(file, "filename", "unknown"),
                    "error": user_friendly_error,
                    "detailed_error": detailed_error[:200],  # 闂傚倸鍊搁崐鎼佸磹閹间礁纾归柛婵勫劗閸嬫挸顫濋悡搴＄睄閻庤娲樼换鍫濐嚕閹绢喖顫呴柣妯挎珪琚ｅ┑鐘茬棄閺夊簱鍋撻弴銏犵柈妞ゆ牗澹曢崑鎾愁潩椤撶偛鎽甸梺鍝勮閸旀垵顕ｉ鍕瀭妞ゆ棁顫夌€垫牠姊绘担瑙勩仧闁告ê銈搁弻濠囨晲閸滀焦缍庡┑鐐叉▕娴滄粎绮绘导鏉戠閺夊牆澧界粙濠氭煕閿濆骸鐏︽慨濠傤煼瀹曟帒顫濋钘変壕闁汇垻顭堢壕濠氭煙閸撗呭笡闁绘挻娲橀妵鍕敇閻旈浠撮梺鍝勵儐缁嬫帡濡?
                    "current": i + 1,
                    "total": total_files
                })
                
                failed_files += 1
        
        # 闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁撻悩鍐蹭画闂佹寧娲栭崐鎼佸垂閸岀偞鐓曠憸搴ㄣ€冮崨瀛樺€块柛顭戝亖娴滄粓鏌熸潏鍓хɑ缁绢厼鐖奸弻娑㈠棘鐠恒剱褔鏌″畝瀣瘈鐎规洟浜堕、姗€鎮╅惉顏呭灴濮婃椽鎮烽弶鎸幮╅梺纭呮珪閿曘垽鎮伴鍢夌喖鎼圭憴鍕啎闂備焦鎮堕崕顖炲礉瀹ュ鏁婇柛娑樼摠閳锋帒霉閿濆洤鍔嬮柛銈傚亾闂備礁顓介弶鍨潎閻庤娲樼换鍌濈亙闂侀€炲苯澧撮柛鈹垮灲楠炴鎷犻懠顒夊悈闂備胶绮崝妤冩崲濠靛棭娼╅柨鏇楀亾闁宠鍨块幃娆撳级閹寸姳妗撻梻浣瑰绾板秹濡甸崟顖氭闁告煭銈呮儓闂備礁鎼惌澶屾崲濠靛棛鏆﹂柟顖炲亰濡查箖姊洪崷顓熸珪濠电偐鍋撻梺?
        print(f"\n{'='*60}")
        print("Log message")
        print("Log message")
        print("Log message")
        print("Log message")
        print("Log message")
        print(f"{'='*60}")
        
        await manager.send_progress_update({
            "type": "all_completed",
            "message": "Operation completed",
            "total_files": total_files,
            "successful_files": successful_files,
            "failed_files": failed_files
        })
        
    except Exception as e:
        detailed_error = log_detailed_exception(
            main_logger,
            "Embedding API test failed",
            e,
            {
                "file_ids": request.file_ids,
                "total_files": total_files,
                "rag_system": request.rag_system,
                "target_database": request.target_database,
                "chunk_size": request.chunk_size,
                "chunk_overlap": request.chunk_overlap,
                "runtime_settings": get_runtime_settings_context(),
            },
        )
        error_msg = "Operation failed"
        print(f"[ERROR] {error_msg}")
        main_logger.error(error_msg)
        await manager.send_progress_update({
            "type": "error",
            "error": error_msg
        })



















