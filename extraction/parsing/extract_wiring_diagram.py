#!/usr/bin/env python3
"""Iterative WiringDiagram extractor using VLM with self-healing capabilities."""

import argparse
import base64
import csv
import hashlib
import json
import logging
import os
import random
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from pydantic import ValidationError

try:
    from parsing.util.structure import Connector, ConnectorPin, Wire, WireGroup, WiringDiagram
except ImportError:
    from util.structure import Connector, ConnectorPin, Wire, WireGroup, WiringDiagram

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


def _resolve_with_root(node, root_schema):
    """Resolve $ref pointers in JSON schema."""
    if not isinstance(node, dict):
        if isinstance(node, list):
            return [_resolve_with_root(item, root_schema) for item in node]
        return node
    
    # Handle $ref (can be standalone or with other fields)
    if '$ref' in node:
        ref_path = node['$ref']
        if ref_path.startswith('#/'):
            parts = ref_path[2:].split('/')
            target = root_schema
            for part in parts:
                if isinstance(target, dict) and part in target:
                    target = target[part]
                else:
                    return {"$unresolved": ref_path}
            resolved = _resolve_with_root(target, root_schema)
            # Merge with other fields except $ref
            result = {k: _resolve_with_root(v, root_schema) for k, v in node.items() if k != '$ref'}
            if isinstance(resolved, dict):
                result.update(resolved)
            return result
    
    return {k: _resolve_with_root(v, root_schema) for k, v in node.items()}


def resolve_json_refs(schema):
    """Resolve all $ref pointers in schema."""
    return _resolve_with_root(schema, schema)


def _format_schema(schema, name=None, indent=0, use_quotes=True, add_desc=True):
    """Format schema with optional model name and quote style.
    
    Args:
        schema: Resolved JSON schema dict
        name: Model name for header (e.g., "Connector"), or None
        indent: Current indentation level
        use_quotes: If True, use "{key}", else use "key"
        add_desc: If True, add description comments. Set False when processing
                  nested fields (parent will add desc).
    """
    spaces = "  " * indent
    type_map = {"string": "str", "integer": "int", "number": "float", "boolean": "bool"}
    
    # Helper to get description safely
    def get_desc(s):
        if not add_desc or 'description' not in s:
            return ""
        return s['description'][:50]
    
    # Object
    if schema.get('type') == 'object' or 'properties' in schema:
        props = schema.get('properties', {})
        required = schema.get('required', [])
        
        if not props:
            return "{}"
        
        # Build header: "ModelName {" or just "{"
        header = f"{name} {{" if name else "{"  
        inner_lines = [header]
        
        for idx, (pname, prop) in enumerate(props.items()):
            # Don't add desc in recursive call for nested fields
            ptype = _format_schema(prop, None, indent + 1, use_quotes, add_desc=False)
            opt = "" if pname in required else " (opt)"
            # Add description at field level
            desc = get_desc(prop)
            comment = f"  # {desc}" if desc else ""
            comma = "," if idx < len(props) - 1 else ""
            
            # Quote or no quote based on use_quotes
            key_str = f'"{pname}"' if use_quotes else pname
            if use_quotes:
                line = f'{spaces}  {key_str}: "{ptype}"{opt}{comment}{comma}'
            else:
                line = f'{spaces}  {key_str}: {ptype}{opt}{comment}'
            inner_lines.append(line)
        
        inner_lines.append(f"{spaces}}}")
        return "\n".join(inner_lines)
    
    # Enum
    if 'enum' in schema:
        vals = schema['enum']
        enum_str = f"enum[{', '.join(repr(str(v)) for v in vals[:5])}{', ...' if len(vals) > 5 else ''}]"
        if add_desc and 'description' in schema:
            desc = schema['description'][:50]
            enum_str += f"  # {desc}"
        return enum_str
    
    # Array
    if schema.get('type') == 'array' or 'items' in schema:
        item_str = _format_schema(schema.get('items', {}), None, indent + 1, use_quotes, add_desc=True)
        result = f"List[{item_str}]"
        if add_desc and 'description' in schema:
            desc = schema['description'][:50]
            result += f"  # {desc}"
        return result
    
    # Simple type - no description here (added at field level if in object)
    return type_map.get(schema.get('type'), 'any')

def format_pydantic_schema(model_class, compact=True):
    """Format a Pydantic model schema.
    
    Args:
        model_class: Pydantic model class
        compact: If True, return compact format {"key": "type"}. 
                If False, return verbose format with model name and comments.
    """
    schema = model_class.model_json_schema()
    resolved = resolve_json_refs(schema)
    
    if compact:
        return _format_schema(resolved, None, 0, use_quotes=True)
    else:
        return _format_schema(resolved, model_class.__name__, 0, use_quotes=False)


# Pre-computed schemas for VLM prompts
CONNECTOR_SCHEMA = format_pydantic_schema(Connector, compact=False)
WIRE_SCHEMA = format_pydantic_schema(Wire, compact=False)
WIRE_GROUP_SCHEMA = format_pydantic_schema(WireGroup, compact=False)
PIN_SCHEMA = format_pydantic_schema(ConnectorPin, compact=False)
FULL_WIRING_DIAGRAM_SCHEMA = format_pydantic_schema(WiringDiagram, compact=True)


class VLMClient:
    """Stateful client for the VLM API (OpenAI-compatible).

    Holds the full conversation history so every extractor turn is a
    follow-up on the same chat. The PDF image is attached once (on the
    priming turn) and the model keeps access to it via context.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:12345",
        model: str = "default",
        system_prompt: Optional[str] = None,
        max_history_tokens: int = 200_000,
        turn_logger: Optional[Any] = None,
    ):
        self.base_url = base_url
        self.model = model
        self.max_history_tokens = max_history_tokens
        self.messages: List[Dict[str, Any]] = []
        self.system_prompt = system_prompt
        if system_prompt:
            self.messages.append({"role": "system", "content": system_prompt})
        # Optional callback: fn(record: dict) -> None. Invoked after every
        # VLM turn with just the new user message + assistant reply (no
        # repeated history).
        self.turn_logger = turn_logger
        if self.turn_logger is not None and system_prompt:
            try:
                self.turn_logger({"kind": "system", "content": system_prompt})
            except Exception as exc:
                logger.warning(f"turn_logger system-init failed: {exc}")

    def reset(self, system_prompt: Optional[str] = None):
        """Reset the conversation. Optionally set a new system prompt."""
        self.messages = []
        if system_prompt:
            self.messages.append({"role": "system", "content": system_prompt})

    def _approx_token_count(self) -> int:
        """Rough token estimate (chars / 4)."""
        total = 0
        for m in self.messages:
            c = m.get("content")
            if isinstance(c, str):
                total += len(c)
            elif isinstance(c, list):
                for part in c:
                    if isinstance(part, dict) and part.get("type") == "text":
                        total += len(part.get("text", ""))
        return total // 4

    def _trim_history(self):
        """Drop oldest non-system messages until under the token cap.

        Keeps the system turn and the first user turn (which carries the
        image + BOM primer) so the model never loses task framing.
        """
        while self._approx_token_count() > self.max_history_tokens and len(self.messages) > 3:
            # index 0 = system, index 1 = primer user turn -> drop index 2
            del self.messages[2]

    def send(
        self,
        user_text: str,
        image_data: Optional[bytes] = None,
        timeout: int = 900,
        parse_json: bool = True,
        max_tokens: Optional[int] = None,
    ) -> Any:
        """Append a user turn, POST the full history, append the assistant
        reply, and return the parsed JSON from the reply (or the raw text
        if parse_json=False).
        """
        content: Any
        if image_data is not None:
            b64 = base64.b64encode(image_data).decode()
            content = [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                {"type": "text", "text": user_text},
            ]
        else:
            content = [{"type": "text", "text": user_text}]

        user_message = {"role": "user", "content": content}
        self.messages.append(user_message)
        self._trim_history()

        # VLM_ENABLE_THINKING=1 → Qwen3 <think> mode ON (default OFF).
        enable_thinking = False # os.environ.get("VLM_ENABLE_THINKING", "0") == "1"
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": self.messages,
            "chat_template_kwargs": {"enable_thinking": enable_thinking},
        }
        # VLM_MAX_TOKENS overrides the per-call max_tokens (useful when
        # thinking is on and the default 32/primer cap is too tight).
        env_mt = os.environ.get("VLM_MAX_TOKENS")
        if env_mt:
            try:
                payload["max_tokens"] = int(env_mt)
            except ValueError:
                pass
        elif max_tokens is not None:
            payload["max_tokens"] = max_tokens

        t_start = time.time()
        error: Optional[str] = None
        data: Dict[str, Any] = {}
        raw = ""
        reasoning = ""
        usage: Dict[str, Any] = {}
        status_code: Optional[int] = None
        try:
            resp = requests.post(
                f"{self.base_url}/v1/chat/completions", json=payload, timeout=timeout
            )
            status_code = resp.status_code
            resp.raise_for_status()
            data = resp.json()
            message = data["choices"][0]["message"]
            # Qwen3 / reasoning models write the final answer to "content" and
            # scratch work to "reasoning_content". Prefer "content".
            raw = message.get("content") or ""
            reasoning = message.get("reasoning_content") or ""
            if not raw and reasoning:
                raw = reasoning
            usage = data.get("usage", {}) or {}
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            raise
        finally:
            elapsed = time.time() - t_start
            if self.turn_logger is not None:
                try:
                    self.turn_logger({
                        "kind": "turn",
                        "elapsed_s": round(elapsed, 3),
                        "timeout_s": timeout,
                        "max_tokens": max_tokens,
                        "model": self.model,
                        "endpoint": f"{self.base_url}/v1/chat/completions",
                        "prompt_has_image": image_data is not None,
                        "image_bytes": len(image_data) if image_data else 0,
                        "user": user_message,
                        "assistant": {"role": "assistant", "content": raw},
                        "response_reasoning": reasoning,
                        "usage": usage,
                        "status_code": status_code,
                        "history_len_before": len(self.messages) - 1,
                        "error": error,
                    })
                except Exception as exc:
                    logger.warning(f"turn_logger failed: {exc}")

        self.messages.append({"role": "assistant", "content": raw})
        if not parse_json:
            return raw
        return self.extract_json_from_text(raw)

    def query(
        self,
        prompt: str,
        image_data: Optional[bytes] = None,
        system_prompt: Optional[str] = None,
        timeout: int = 300,
        log_turn: bool = False,
    ) -> Dict[str, Any]:
        """One-shot query (stateless; leaves self.messages untouched).

        Args:
            log_turn: If True, invoke self.turn_logger so the call appears
                      in vlm_turns.jsonl alongside conversational turns.
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if image_data:
            b64 = base64.b64encode(image_data).decode()
            user_msg = {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                {"type": "text", "text": prompt},
            ]}
        else:
            user_msg = {"role": "user", "content": [{"type": "text", "text": prompt}]}
        messages.append(user_msg)

        payload = {"model": self.model, 
                    "messages": messages,
                    "chat_template_kwargs": {"enable_thinking": False},
        }

        t_start = time.time()
        error: Optional[str] = None
        raw = ""
        reasoning = ""
        usage: Dict[str, Any] = {}
        status_code: Optional[int] = None
        try:
            resp = requests.post(f"{self.base_url}/v1/chat/completions", json=payload, timeout=timeout)
            status_code = resp.status_code
            resp.raise_for_status()
            data = resp.json()
            message = data["choices"][0]["message"]
            raw = message.get("content") or ""
            reasoning = message.get("reasoning_content") or ""
            if not raw and reasoning:
                raw = reasoning
            usage = data.get("usage", {}) or {}
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            raise
        finally:
            elapsed = time.time() - t_start
            if log_turn and self.turn_logger is not None:
                try:
                    self.turn_logger({
                        "kind": "turn",
                        "elapsed_s": round(elapsed, 3),
                        "timeout_s": timeout,
                        "max_tokens": None,
                        "model": self.model,
                        "endpoint": f"{self.base_url}/v1/chat/completions",
                        "prompt_has_image": image_data is not None,
                        "image_bytes": len(image_data) if image_data else 0,
                        "user": user_msg,
                        "assistant": {"role": "assistant", "content": raw},
                        "response_reasoning": reasoning,
                        "usage": usage,
                        "status_code": status_code,
                        "history_len_before": 0,
                        "error": error,
                    })
                except Exception as exc:
                    logger.warning(f"turn_logger (query) failed: {exc}")

        content = raw
        return self.extract_json_from_text(content)

    def extract_json_from_text(self, text: str):
        """Extract JSON from text that may contain markdown or explanations."""
        text = text.strip()
        
        # Try markdown code blocks with much broader regex for lists or objects
        match = re.search(r'```(?:json)?\s*([\s\S]*?)```', text, re.DOTALL)
        if match:
            try:
                candidate = match.group(1).strip()
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass
        
        # Fallback 1: Direct JSON load (no blocks)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        
        # Fallback 2: Regex for anything between { } or [ ]
        match = re.search(r'([\{\[][\s\S]*[\}\]])', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except:
                pass
        
        raise ValueError(f"Could not extract JSON from: {text[:100]}...")


# ---------------------------------------------------------------------------
# BOM (Bill of Materials) parser
# ---------------------------------------------------------------------------

def parse_bom_csv(csv_path: str) -> Dict[str, Any]:
    """
    Parse a semicolon-separated BOM CSV file.

    Returns a dict with:
        connectors: list of {part_name, part_number}
        wires:      list of {part_name, part_number, length_mm}
    """
    connectors = []
    wires = []
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter=";")
            for row in reader:
                row_type = row.get("type", "").strip().lower()
                if row_type == "connector":
                    connectors.append({
                        "part_name": row.get("part_name", "").strip(),
                        "part_number": row.get("part_number", "").strip(),
                    })
                elif row_type == "wire":
                    try:
                        length = float(row.get("value", "0"))
                    except ValueError:
                        length = 0.0
                    wires.append({
                        "part_name": row.get("part_name", "").strip(),
                        "part_number": row.get("part_number", "").strip(),
                        "length_mm": length,
                    })
    except Exception as e:
        logger.warning(f"Failed to parse BOM CSV {csv_path}: {e}")
    return {"connectors": connectors, "wires": wires}


def format_bom_for_prompt(bom: Dict[str, Any]) -> str:
    """Format BOM data as a readable string for VLM prompts."""
    lines = ["=== Bill of Materials (BOM) ==="]
    if bom["connectors"]:
        lines.append("Connectors:")
        for c in bom["connectors"]:
            lines.append(f"  - {c['part_name']}: part_number={c['part_number']}")
    if bom["wires"]:
        lines.append("Wires:")
        for w in bom["wires"]:
            lines.append(f"  - {w['part_name']}: part_number={w['part_number']}, length={w['length_mm']}mm")
    return "\n".join(lines)


class WiringDiagramExtractor:
    """Iterative VLM-based extraction with self-healing."""
    
    def __init__(
        self,
        pdf_path: str,
        csv_path: str = None,
        output_path: str = None,
        vlm_url: str = None,
        vlm_model: str = "default",
        verbose: bool = False,
        log_dir: str = None,
    ):
        self.pdf_path = Path(pdf_path)
        self.csv_path = Path(csv_path) if csv_path else None
        self.output_path = Path(output_path) if output_path else self.pdf_path.with_suffix('.json')
        self.verbose = verbose
        self.log_dir = Path(log_dir) if log_dir else None
        self._vlm_log_counter = 0
        self._turn_idx = 0
        self._current_phase: str = "unset"
        self._current_batch: int = 0

        # Load BOM from CSV
        self.bom: Dict[str, Any] = {"connectors": [], "wires": []}
        if self.csv_path and self.csv_path.exists():
            self.bom = parse_bom_csv(str(self.csv_path))
            logger.info(f"Loaded BOM: {len(self.bom['connectors'])} connectors, {len(self.bom['wires'])} wires")

        self.bom_text = format_bom_for_prompt(self.bom) if (self.bom["connectors"] or self.bom["wires"]) else ""

        # Fast lookup: BOM part_name → part_number (used for Wire.part_number backfill).
        self._bom_wire_part_number: Dict[str, str] = {
            w["part_name"]: w["part_number"] for w in self.bom.get("wires", []) if w.get("part_name")
        }

        self.system_prompt = f"""You are a technical diagram analyzer specialized in extracting wiring information from automotive electrical schematics (Stromlaufplan).

Your task is to analyze the provided wiring diagram image and extract all structural information into a structured JSON format. The extraction process is split into multiple subtasks. Adhere to each subtask precisely.

### Output Discipline:
- NEVER explain reasoning. NEVER add commentary.
- Output ONLY the requested JSON array or object.
- If you cannot determine a field, use "unknown" for strings or null for numbers.

### Wire Colors:
- Valid: green, blue, red, orange, yellow, white, black, brown, gray, unknown
- If unclear, use "unknown"
- For tracer wires (e.g., green with white stripe), use the dominant color (green)

### IDs:
- For connector_id: use the connector's label exactly as printed in the diagram (e.g., "X1", "ST1", "J3"). Do not invent IDs.
- For wire_id: use the wire's BOM part_name (e.g. "W0001") when cross-referenceable, else a short descriptive placeholder.

### Complete WiringDiagram Schema (JSON Schema with $defs):
{FULL_WIRING_DIAGRAM_SCHEMA}"""

        self.vlm = VLMClient(
            vlm_url,
            model=vlm_model,
            system_prompt=self.system_prompt,
            turn_logger=self._vlm_turn_logger,
        )

        self.page_images: List[bytes] = []
        self._load_pdf_images()

        self.accumulated_connectors: List[Connector] = []
        self.accumulated_wires: List[Wire] = []

        self._primed = False

    def _prime_conversation(self):
        """Seed the VLM conversation with the BOM and the PDF page image.

        This is the only turn where the image is uploaded. All subsequent
        extractor prompts refer back to it implicitly via conversation
        history.
        """
        if self._primed or not self.page_images:
            return

        n_conn = len(self.bom.get("connectors", []))
        n_wire = len(self.bom.get("wires", []))
        primer = f"""I will ask you to extract structured data from this wiring diagram in several subtasks.
Use the attached image and the BOM below as the authoritative sources.

{self.bom_text if self.bom_text else "(no BOM provided)"}

The BOM lists {n_conn} connector(s) and {n_wire} wire(s). The part_name values
(e.g. "C000", "W0001") are the labels you will see in the diagram; the
part_number values (e.g. "TE-6P", "FLRY-0.35-RD") are the component types.

Do NOT extract anything yet. Reply with EXACTLY the single word: READY
/no_think"""
        self._current_phase = "primer"
        self._current_batch = 0
        response = self.vlm.send(
            primer,
            image_data=self.page_images[0],
            parse_json=False,
            max_tokens=32,
        )
        self._log_vlm("primer", 0, primer, response)
        self._primed = True

    def _log_vlm(self, phase: str, batch: int, prompt: str, response: Any):
        """Log a VLM interaction to a JSONL file in log_dir."""
        if not self.log_dir:
            return
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._vlm_log_counter += 1
        log_file = self.log_dir / "vlm_log.jsonl"
        entry = {
            "seq": self._vlm_log_counter,
            "turn_idx": self._turn_idx,
            "phase": phase,
            "batch": batch,
            "prompt_preview": prompt[:500],
            "response": response if isinstance(response, (dict, list)) else str(response),
        }
        try:
            with open(log_file, "a") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        except Exception as e:
            logger.warning(f"Failed to write VLM log: {e}")

    def _vlm_turn_logger(self, record: Dict[str, Any]):
        """Callback from VLMClient: append one turn record to vlm_turns.jsonl.

        Writes a single JSONL file `<log_dir>/vlm_turns.jsonl`. The first
        line is the system prompt (kind="system"); each subsequent line is
        one conversational turn (kind="turn") with just the new user
        message and the assistant reply — no repeated history. Concatenating
        [system] + [turn.user, turn.assistant for each turn] reconstructs
        the exact conversation.
        """
        if not self.log_dir:
            return
        self.log_dir.mkdir(parents=True, exist_ok=True)
        log_file = self.log_dir / "vlm_turns.jsonl"

        kind = record.get("kind", "turn")
        if kind == "system":
            entry = {
                "kind": "system",
                "content": record.get("content"),
            }
        else:
            self._turn_idx += 1
            entry = {
                "kind": "turn",
                "turn_idx": self._turn_idx,
                "phase": self._current_phase,
                "batch": self._current_batch,
                "model": record.get("model"),
                "endpoint": record.get("endpoint"),
                "elapsed_s": record.get("elapsed_s"),
                "timeout_s": record.get("timeout_s"),
                "max_tokens": record.get("max_tokens"),
                "status_code": record.get("status_code"),
                "prompt_has_image": record.get("prompt_has_image"),
                "image_bytes": record.get("image_bytes"),
                "user": record.get("user"),
                "assistant": record.get("assistant"),
                "response_reasoning": record.get("response_reasoning"),
                "usage": record.get("usage"),
                "error": record.get("error"),
            }
        try:
            with open(log_file, "a") as f:
                f.write(json.dumps(entry, default=str, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"Failed to write VLM turns log: {e}")

    def _load_pdf_images(self):
        """Convert PDF to images using PyMuPDF."""
        try:
            import fitz
            doc = fitz.open(self.pdf_path)
            for page_num in range(len(doc)):
                page = doc[page_num]
                mat = fitz.Matrix(2.0, 2.0)
                pix = page.get_pixmap(matrix=mat)
                self.page_images.append(pix.tobytes("png"))
            logger.info(f"Loaded {len(self.page_images)} page(s) from PDF")
            doc.close()
        except ImportError:
            logger.error("PyMuPDF (fitz) required: pip install pymupdf")
            sys.exit(1)
        except Exception as e:
            logger.error(f"Failed to load PDF: {e}")
            raise
    
    def hydrate_from_run_dir(self, run_dir: Path) -> bool:
        """Reload extractor state from a prior first-pass run.

        Rebuilds `self.vlm.messages`, `self.accumulated_connectors`, and
        `self.accumulated_wires` from `run_dir/first_pass.json` and
        `run_dir/vlm_turns.jsonl` so that subsequent phases (healing) pick
        up where the first pass stopped. Returns True on success.

        Only the LAST complete first-pass conversation in the jsonl is
        replayed — earlier appended conversations (from re-runs) are
        ignored. The marker is the latest `phase=primer, batch=0` turn.
        """
        run_dir = Path(run_dir)
        fp_path = run_dir / "first_pass.json"
        turns_path = run_dir / "vlm_turns.jsonl"
        if not fp_path.exists() or not turns_path.exists():
            return False

        # 1. Rebuild accumulated connectors + wires from first_pass.json.
        fp_data = json.loads(fp_path.read_text())
        self.accumulated_connectors = [
            Connector(**c) for c in fp_data.get("connectors", [])
        ]
        self.accumulated_wires = [Wire(**w) for w in fp_data.get("wires", [])]

        # 2. Load all turns, then slice to the last first-pass conversation.
        turns: List[Dict[str, Any]] = []
        with open(turns_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    turns.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        last_primer_idx = None
        for i, t in enumerate(turns):
            if t.get("kind") == "turn" and t.get("phase") == "primer" and t.get("batch") == 0:
                last_primer_idx = i
        if last_primer_idx is None:
            logger.warning(f"hydrate: no primer turn found in {turns_path}")
            return False

        conv_turns = [t for t in turns[last_primer_idx:] if t.get("kind") == "turn"]

        # 3. Rebuild self.vlm.messages: system + (user, assistant) per turn.
        self.vlm.messages = []
        if self.system_prompt:
            self.vlm.messages.append({"role": "system", "content": self.system_prompt})
        for t in conv_turns:
            user_msg = t.get("user")
            asst_msg = t.get("assistant")
            if isinstance(user_msg, dict) and user_msg.get("role") == "user":
                self.vlm.messages.append(user_msg)
            if isinstance(asst_msg, dict) and asst_msg.get("role") == "assistant":
                self.vlm.messages.append(asst_msg)

        # Advance turn counter so newly-logged turns don't collide.
        self._turn_idx = max(
            (t.get("turn_idx", 0) for t in turns if t.get("kind") == "turn"),
            default=0,
        )
        self._primed = True

        logger.info(
            f"hydrate: restored {len(self.accumulated_connectors)} connectors, "
            f"{len(self.accumulated_wires)} wires, "
            f"{len(conv_turns)} conversation turns from {run_dir}"
        )
        return True

    def enrich_from_first_pass(self, run_dir: Path) -> Optional[WiringDiagram]:
        """Resume from a first-pass run dir, run healing, save enriched.json.

        Assumes `run_dir` contains `first_pass.json` + `vlm_turns.jsonl`
        from an earlier first-pass extraction. Loads that state, runs the
        self-healing phase on the existing VLM conversation, then
        assembles and saves the enriched WiringDiagram to self.output_path.
        """
        if not self.hydrate_from_run_dir(run_dir):
            logger.error(f"enrich_from_first_pass: could not hydrate from {run_dir}")
            return None

        logger.info("Phase 3: Self-healing validation (resumed)...")
        self._heal_missing_references()

        logger.info("Phase 4: Assembling enriched WiringDiagram...")
        diagram = self._assemble_diagram()
        self._save_output(diagram)
        logger.info(
            f"Enrichment complete: {len(diagram.connectors)} connectors, "
            f"{len(diagram.wires)} wires"
        )
        return diagram

    def extract(self) -> WiringDiagram:
        """Main extraction pipeline."""
        logger.info("Starting WiringDiagram extraction...")

        if not self.page_images:
            logger.error("No images available from PDF")
            return None

        # Phase 0: Prime the conversation with the PDF image + BOM.
        self._prime_conversation()

        # Phase 1: Extract connectors (single-pass)
        logger.info("Phase 1: Extracting connectors (single-pass)...")
        self._extract_connectors_single_pass()
        logger.info(f"  Extracted {len(self.accumulated_connectors)} connectors")

        # Phase 2: Extract wires (single-pass)
        logger.info("Phase 2: Extracting wires (single-pass)...")
        self._extract_wires_single_pass()
        logger.info(f"  Extracted {len(self.accumulated_wires)} wires")

        # Phase 3: Self-healing
        logger.info("Phase 3: Self-healing validation...")
        self._heal_missing_references()

        # Phase 4: Assemble
        logger.info("Phase 4: Assembling WiringDiagram...")
        diagram = self._assemble_diagram()

        self._save_output(diagram)

        logger.info(f"Extraction complete: {len(diagram.connectors)} connectors, "
                   f"{len(diagram.wires)} wires")
        return diagram

    # ------------------------------------------------------------------
    # Phase 1: Single-pass connector extraction
    # ------------------------------------------------------------------

    def _extract_connectors_single_pass(self):
        """Extract all connectors in one VLM turn.

        The VLM already has the BOM and image from the primer turn.
        Retry once on JSON-extraction failure or zero-validated result.
        """
        bom_n = len(self.bom.get("connectors", []))

        prompt = f"""Subtask 1: Extract ALL connectors at once.

Each connector is a labeled rectangle on the diagram containing numbered
circles (pins). The visible label becomes `connector_id`; the BOM's
`part_number` becomes `connector_name`.

Schema:
{CONNECTOR_SCHEMA}

Rules:
1. `connector_id` = the label printed inside the box (e.g. "C000", "X1").
2. `connector_name` = the BOM `part_number` matching that connector (e.g. "TE-6P").
3. `pin_count` = count ONLY the pin circles/slots you can visually see drawn inside
   the connector box in the diagram. Do NOT guess the pin count from the connector
   name — the name is just a label and does not encode the number of pins.
4. `connector_type`: "power_connector" for power, "signal_connector" for signals, "module_connector" for modules. If unsure, use "signal_connector".
5. The BOM lists {bom_n} connector(s). Return ALL of them in ONE JSON array.

Return ONLY a JSON array of ALL connector objects:
```json
[...]
```

/no_think"""

        for attempt_num in range(2):  # attempt 0 = first try, 1 = retry
            try:
                self._current_phase = "connector"
                self._current_batch = attempt_num + 1
                if self.verbose:
                    logger.info(f"PROMPT: {prompt[:200]}...")
                response = self.vlm.send(prompt)
                self._log_vlm("connector", attempt_num + 1, prompt, response)

                # Unwrap single-key dict wrapping (e.g. {"connectors": [...]})
                response = self._unwrap_single_key_list(response)

                valid = self._validate_connector_batch(response)
                if valid:
                    # Dedup by connector_id
                    seen_ids = set()
                    deduped = []
                    for c in valid:
                        if c.connector_id not in seen_ids:
                            seen_ids.add(c.connector_id)
                            deduped.append(c)
                    self.accumulated_connectors = deduped
                    logger.info(f"    Connector single-pass: {len(deduped)} valid (attempt {attempt_num + 1})")
                    return  # success
                else:
                    logger.warning(f"    Zero valid connectors on attempt {attempt_num + 1}")
            except Exception as e:
                logger.error(f"    Connector extraction attempt {attempt_num + 1} failed: {e}")

            # Retry prompt
            if attempt_num == 0:
                prompt = f"""Your previous reply could not be parsed or produced zero valid connectors.
Return ONLY a JSON array of ALL {bom_n} connector objects. No commentary.
```json
[...]
```

/no_think"""

    # ------------------------------------------------------------------
    # Phase 2: Single-pass wire extraction
    # ------------------------------------------------------------------

    def _extract_wires_single_pass(self):
        """Extract all wires in one VLM turn.

        Includes the full BOM wire list, known connector IDs, and asks for
        exactly M Wire objects. Retry once on failure.
        """
        wires_bom = self.bom.get("wires", [])
        if not wires_bom:
            logger.info("  No wires in BOM, skipping wire extraction")
            return

        known_ids = ", ".join(c.connector_id for c in self.accumulated_connectors) or "(none)"

        # Build a readable wire list from BOM
        bom_wire_lines = []
        for w_bom in wires_bom:
            pname = w_bom.get("part_name", "")
            pnum = w_bom.get("part_number", "")
            color_hint = self._color_from_part_number(pnum) or "unknown"
            bom_wire_lines.append(f"  - {pname}: part_number={pnum}, expected_color={color_hint}")
        bom_wire_text = "\n".join(bom_wire_lines)

        n_wires = len(wires_bom)
        # Compute max_tokens: enough for large wire lists
        max_tok = max(4096, 200 * n_wires)

        prompt = f"""Subtask 2: Extract ALL wires at once.

Known connector_id values (use ONLY these as source/destination): {known_ids}

BOM wire list ({n_wires} wires):
{bom_wire_text}

Schema:
{WIRE_SCHEMA}

Rules:
1. `source_connector_id` / `destination_connector_id` MUST be one of the known
   connector_id values above. Do not invent IDs.
2. `source_pin_number` / `destination_pin_number` = the numbered pin (1-indexed)
   the wire terminates on.
3. `wire_id` = the BOM `part_name` for that specific wire.
4. `color`: one of green, blue, red, orange, yellow, white, black, brown, gray, unknown.
   The BOM part_number suffix encodes the color (RD=red, BU=blue, GN=green,
   YE=yellow, BK=black, WH=white, OG=orange, BR=brown, GY=gray).
5. `gauge` = float mm² (optional). Null if unknown.

Return ONLY a JSON array of exactly {n_wires} Wire objects, one per BOM wire:
```json
[...]
```

/no_think"""

        for attempt_num in range(2):
            try:
                self._current_phase = "wire"
                self._current_batch = attempt_num + 1
                if self.verbose:
                    logger.info(f"PROMPT: {prompt[:200]}...")
                response = self.vlm.send(prompt, max_tokens=max_tok)
                self._log_vlm("wire", attempt_num + 1, prompt, response)

                # Unwrap single-key dict wrapping (e.g. {"wires": [...]})
                response = self._unwrap_single_key_list(response)

                valid = self._validate_wire_batch(response)

                # Soften wire_id overwrite: only fix empty/unknown wire_ids
                bom_names = {w["part_name"] for w in wires_bom}
                for w in valid:
                    if not w.wire_id or w.wire_id == "unknown":
                        # Try to match by part_number
                        for wb in wires_bom:
                            if wb["part_number"] == w.part_number:
                                w.wire_id = wb["part_name"]
                                break

                if valid:
                    # Dedup by (wire_id, src, src_pin, dst, dst_pin)
                    seen = set()
                    deduped = []
                    for w in valid:
                        key = (w.wire_id, w.source_connector_id, w.source_pin_number,
                               w.destination_connector_id, w.destination_pin_number)
                        if key not in seen:
                            seen.add(key)
                            deduped.append(w)
                    self.accumulated_wires = deduped
                    logger.info(f"    Wire single-pass: {len(deduped)} valid (attempt {attempt_num + 1})")
                    return
                else:
                    logger.warning(f"    Zero valid wires on attempt {attempt_num + 1}")
            except Exception as e:
                logger.error(f"    Wire extraction attempt {attempt_num + 1} failed: {e}")

            # Retry prompt
            if attempt_num == 0:
                prompt = f"""Your previous reply could not be parsed or produced zero valid wires.
Return ONLY a JSON array of exactly {n_wires} Wire objects, one per BOM wire.
Known connector_ids: {known_ids}
No commentary.
```json
[...]
```

/no_think"""

    # ------------------------------------------------------------------
    # Unwrap helper
    # ------------------------------------------------------------------

    @staticmethod
    def _unwrap_single_key_list(data):
        """If data is a single-key dict whose value is a list, unwrap it.

        VLMs sometimes reply {"connectors": [...]} or {"wires": [...]}.
        """
        if isinstance(data, dict) and len(data) == 1:
            val = next(iter(data.values()))
            if isinstance(val, list):
                return val
        return data

    # ------------------------------------------------------------------
    # Phase 3: Self-healing
    # ------------------------------------------------------------------

    def _case_seed(self) -> int:
        """Version-stable seed derived from the PDF filename.

        Used for the conflict random-pick so two runs of the same case
        produce byte-identical enriched.json.
        """
        return int.from_bytes(
            hashlib.blake2b(self.pdf_path.stem.encode(), digest_size=4).digest(),
            "big",
        )

    def _heal_missing_references(self):
        """Self-healing loop: all detectors run every attempt (no elif chain).

        Only asymmetric detectors run — each touches wires only when
        independent structural evidence flags them as broken. Symmetric
        VLM second-guessing phases (verify, missing-BOM) were removed
        after they were measured to be net-negative on F1.
        """
        max_attempts = 3
        seed = self._case_seed()

        for attempt in range(max_attempts):
            n = 0
            n += self._heal_dedup()
            n += self._heal_spurious_wires()
            n += self._heal_orphans(attempt, final=(attempt == max_attempts - 1))
            n += self._heal_pin_conflicts(attempt, seed=seed)
            n += self._heal_empty_connectors()

            if n == 0 and self._all_detectors_clean():
                logger.info(f"  All detectors clean after attempt {attempt + 1}")
                break
            else:
                logger.info(f"  Healing attempt {attempt + 1}: {n} actions taken")

        logger.info(f"  Self-healing complete")

    # ------------------------------------------------------------------
    # Detector: dedup identical wires
    # ------------------------------------------------------------------

    def _heal_dedup(self) -> int:
        """Collapse exact-duplicate wires. No VLM. Returns dropped count."""
        seen = set()
        deduped = []
        dropped = 0
        for w in self.accumulated_wires:
            key = (w.wire_id, w.source_connector_id, w.source_pin_number,
                   w.destination_connector_id, w.destination_pin_number)
            if key in seen:
                dropped += 1
                logger.info(f"    dedup: dropped duplicate {w.wire_id} "
                           f"{w.source_connector_id}:{w.source_pin_number} -> "
                           f"{w.destination_connector_id}:{w.destination_pin_number}")
            else:
                seen.add(key)
                deduped.append(w)
        self.accumulated_wires = deduped
        return dropped

    # ------------------------------------------------------------------
    # Detector: remove wires not in BOM
    # ------------------------------------------------------------------

    def _heal_spurious_wires(self) -> int:
        """Remove any wire whose wire_id is not in the BOM. No VLM."""
        bom_names = set(self._bom_wire_part_number.keys())
        if not bom_names:
            return 0  # no BOM → nothing to check
        kept = []
        dropped = 0
        for w in self.accumulated_wires:
            if w.wire_id in bom_names:
                kept.append(w)
            else:
                dropped += 1
                logger.info(f"    spurious: dropped {w.wire_id} (not in BOM)")
        self.accumulated_wires = kept
        return dropped

    # ------------------------------------------------------------------
    # Detector: orphan wires (referencing unknown connector IDs)
    # ------------------------------------------------------------------

    def _heal_orphans(self, attempt: int, final: bool = False) -> int:
        """Fix or drop wires referencing non-existent connector IDs."""
        known_ids = {c.connector_id for c in self.accumulated_connectors}
        known_ids_str = ", ".join(sorted(known_ids))
        orphans = []
        for wire in self.accumulated_wires:
            src_ok = wire.source_connector_id in known_ids
            dst_ok = wire.destination_connector_id in known_ids
            if not src_ok or not dst_ok:
                orphans.append({
                    "wire": wire,
                    "missing_source": not src_ok,
                    "missing_destination": not dst_ok,
                })

        if not orphans:
            return 0

        healed = 0
        to_drop = []
        for orphan in orphans:
            wire = orphan["wire"]
            issues = []
            if orphan["missing_source"]:
                issues.append(f"source_connector_id '{wire.source_connector_id}' is not in the known list")
            if orphan["missing_destination"]:
                issues.append(f"destination_connector_id '{wire.destination_connector_id}' is not in the known list")

            prompt = f"""Correction: earlier in our conversation you reported
wire `{wire.wire_id}` as `{wire.source_connector_id}:{wire.source_pin_number} -> {wire.destination_connector_id}:{wire.destination_pin_number}`.
Problem: {"; ".join(issues)}.

Valid connector_ids are ONLY these: {known_ids_str}

Look again at the diagram and correct this wire. Return ONLY:
```json
{{
  "source_connector_id": "<one of the valid ids or null>",
  "destination_connector_id": "<one of the valid ids or null>"
}}
```

/no_think"""
            try:
                self._current_phase = "heal_orphan"
                self._current_batch = attempt + 1
                response = self.vlm.send(prompt)
                self._log_vlm("heal_orphan", attempt + 1, prompt, response)
                if isinstance(response, dict):
                    corrected_src = response.get("source_connector_id")
                    corrected_dst = response.get("destination_connector_id")
                    applied = False
                    if corrected_src and corrected_src in known_ids:
                        wire.source_connector_id = corrected_src
                        applied = True
                    if corrected_dst and corrected_dst in known_ids:
                        wire.destination_connector_id = corrected_dst
                        applied = True
                    if applied:
                        logger.info(f"    orphan healed: {wire.wire_id} -> "
                                   f"{wire.source_connector_id}:{wire.source_pin_number} to "
                                   f"{wire.destination_connector_id}:{wire.destination_pin_number}")
                        healed += 1
                    elif final:
                        to_drop.append(wire)
                elif final:
                    to_drop.append(wire)
            except Exception as e:
                logger.warning(f"    Failed to heal orphan {wire.wire_id}: {e}")
                if final:
                    to_drop.append(wire)

        # Drop unresolved orphans on final attempt
        for w in to_drop:
            if w in self.accumulated_wires:
                self.accumulated_wires.remove(w)
                healed += 1
                logger.info(f"    orphan dropped (final): {w.wire_id}")

        return healed

    # ------------------------------------------------------------------
    # Detector: pin conflicts
    # ------------------------------------------------------------------

    def _heal_pin_conflicts(self, attempt: int, seed: int) -> int:
        """Resolve pin conflicts: multiple wires on the same pin.

        On VLM retry failure, randomly pick one wire to keep and drop
        the rest (deterministic via seed).
        """
        known_ids = {c.connector_id for c in self.accumulated_connectors}
        healed = 0

        # Rebuild occupancy fresh each time
        pin_occupancy = {}
        for wire in self.accumulated_wires:
            src_key = (wire.source_connector_id, wire.source_pin_number)
            dst_key = (wire.destination_connector_id, wire.destination_pin_number)
            if src_key[0] and src_key[1]:
                pin_occupancy.setdefault(src_key, []).append((wire, 'source'))
            if dst_key[0] and dst_key[1]:
                pin_occupancy.setdefault(dst_key, []).append((wire, 'destination'))

        conflicts = []
        for (cid, pin), wires_endpoints in pin_occupancy.items():
            if len(wires_endpoints) > 1:
                conflicts.append({
                    "connector_id": cid,
                    "pin_number": pin,
                    "conflicting": wires_endpoints,
                })

        if not conflicts:
            return 0

        # Sort conflicts for deterministic ordering
        conflicts.sort(key=lambda c: (c["connector_id"], c["pin_number"]))

        known_ids_str = ", ".join(sorted(known_ids))

        for conflict in conflicts:
            cid = conflict["connector_id"]
            pin = conflict["pin_number"]

            # Check if conflict is still live (wires may have been removed
            # by a prior conflict resolution in this iteration)
            live_wires = [(w, s) for (w, s) in conflict["conflicting"]
                          if w in self.accumulated_wires]
            if len(live_wires) <= 1:
                continue

            wires_involved = [w.wire_id for w, _ in live_wires]
            wire_names_str = ", ".join(f"`{w}`" for w in wires_involved)

            prompt = f"""You are an expert electrical QA engineer. Multiple wires ({wire_names_str}) are mapped to exactly the same pin `{pin}` on connector `{cid}`. 
In these diagrams, a pin can only hold ONE wire natively. One of these wires is correctly assigned, and the other is wrongly assigned here.

Carefully look at connector `{cid}` in the diagram. Decide which wire is WRONG, and return ONLY the corrected connection for the WRONG wire(s).

Return ONLY a JSON array with one object per WRONG wire, specifying its correct connector and pin:
```json
[
  {{ "wire_id": "<wire_id>", "source_connector_id": "<id>", "source_pin_number": <pin>, "destination_connector_id": "<id>", "destination_pin_number": <pin> }}
]
```
/no_think"""

            applied = self._attempt_conflict_fix(
                prompt, conflict, live_wires, pin_occupancy, known_ids,
                attempt, is_retry=False, seed=seed,
            )
            healed += applied

        return healed

    def _attempt_conflict_fix(
        self, prompt, conflict, live_wires, pin_occupancy, known_ids,
        attempt, is_retry, seed,
    ) -> int:
        """Try to fix a pin conflict via VLM; random-pick on failure."""
        cid = conflict["connector_id"]
        pin = conflict["pin_number"]

        try:
            phase_name = "heal_conflict_retry" if is_retry else "heal_conflict"
            self._current_phase = phase_name
            self._current_batch = attempt + 1
            response = self.vlm.send(prompt)
            self._log_vlm(phase_name, attempt + 1, prompt, response)

            if isinstance(response, list):
                applied = 0
                for c_wire in response:
                    wid = c_wire.get("wire_id")
                    for w, side in live_wires:
                        if w.wire_id == wid and w in self.accumulated_wires:
                            new_src = c_wire.get("source_connector_id")
                            new_pin_src = c_wire.get("source_pin_number")
                            new_dst = c_wire.get("destination_connector_id")
                            new_pin_dst = c_wire.get("destination_pin_number")

                            # Dry-run: check new destination isn't already occupied
                            def get_occupant(check_cid, check_pin, exclude_wid):
                                if not check_cid or not check_pin:
                                    return None
                                occupants = [
                                    occ[0].wire_id
                                    for occ in pin_occupancy.get((check_cid, check_pin), [])
                                    if occ[0].wire_id != exclude_wid and occ[0] in self.accumulated_wires
                                ]
                                return occupants[0] if occupants else None

                            occ_src = get_occupant(new_src, new_pin_src, wid) if new_src and new_pin_src else None
                            occ_dst = get_occupant(new_dst, new_pin_dst, wid) if new_dst and new_pin_dst else None

                            if occ_src or occ_dst:
                                bad_pin = f"{new_src}:{new_pin_src}" if occ_src else f"{new_dst}:{new_pin_dst}"
                                occupant = occ_src if occ_src else occ_dst
                                logger.warning(f"    Dry run rejected. VLM tried to move {wid} to {bad_pin}, but it is occupied by {occupant}.")

                                if not is_retry:
                                    reject_prompt = f"""Dry Run Failed: You tried to move `{wid}` to `{bad_pin}`, but that pin is ALREADY occupied by `{occupant}`!
Your correction created a new conflict. Please analyze again and find the TRULY empty and correct pin for `{wid}`. 
Return ONLY the corrected JSON array block.
/no_think"""
                                    return self._attempt_conflict_fix(
                                        reject_prompt, conflict, live_wires,
                                        pin_occupancy, known_ids, attempt,
                                        is_retry=True, seed=seed,
                                    )
                                else:
                                    # Retry also failed → fall through to random-pick
                                    break

                            # Apply the fix
                            if new_src in known_ids:
                                w.source_connector_id = new_src
                                if new_pin_src:
                                    w.source_pin_number = int(new_pin_src)
                            if new_dst in known_ids:
                                w.destination_connector_id = new_dst
                                if new_pin_dst:
                                    w.destination_pin_number = int(new_pin_dst)

                            logger.info(f"    conflict healed {wid} -> "
                                       f"{w.source_connector_id}:{w.source_pin_number} to "
                                       f"{w.destination_connector_id}:{w.destination_pin_number}")
                            applied += 1
                if applied > 0:
                    return applied
            # VLM didn't return a useful list → fall through to random-pick
        except Exception as e:
            logger.warning(f"    Failed to heal conflict {cid}:{pin}: {e}")

        # Random-pick fallback: keep one, drop the rest
        return self._random_pick_conflict(conflict, live_wires, seed)

    def _random_pick_conflict(self, conflict, live_wires, seed: int) -> int:
        """Pick one wire to keep on a pin, drop the rest.

        Tie-break by BOM color first: a wire whose extracted color matches
        the color encoded in its part_number is more trustworthy than one
        whose color disagrees. If the split is decisive (some wires match,
        others mismatch) keep a matcher; otherwise fall back to the
        seeded-random pick.
        """
        cid = conflict["connector_id"]
        pin = conflict["pin_number"]
        candidates = [w for w, _ in live_wires if w in self.accumulated_wires]
        if len(candidates) <= 1:
            return 0

        matches = []
        mismatches = []
        for w in candidates:
            expected = self._color_from_part_number(w.part_number)
            if expected is None:
                continue
            if w.color.value == expected:
                matches.append(w)
            else:
                mismatches.append(w)

        rng = random.Random(seed ^ (hash((cid, pin)) & 0xFFFFFFFF))
        if matches and mismatches:
            keeper = matches[0] if len(matches) == 1 else rng.choice(matches)
            reason = f"bom-color-match (match={[m.wire_id for m in matches]} mismatch={[m.wire_id for m in mismatches]})"
        else:
            keeper = rng.choice(candidates)
            reason = f"seed={seed}"

        dropped = 0
        for w in candidates:
            if w is not keeper and w in self.accumulated_wires:
                self.accumulated_wires.remove(w)
                dropped += 1
                logger.info(f"    conflict {cid}:{pin} unresolved; dropped {w.wire_id} ({reason})")
        return dropped

    # ------------------------------------------------------------------
    # Detector: empty connectors (no wires attached)
    # ------------------------------------------------------------------

    def _heal_empty_connectors(self) -> int:
        """Find wires for connectors that have no wires attached."""
        if not self.page_images:
            return 0

        connected_cids = set()
        for w in self.accumulated_wires:
            if w.source_connector_id:
                connected_cids.add(w.source_connector_id)
            if w.destination_connector_id:
                connected_cids.add(w.destination_connector_id)

        empty = [c for c in self.accumulated_connectors
                 if c.connector_id not in connected_cids]
        if not empty:
            return 0

        known_ids = sorted(c.connector_id for c in self.accumulated_connectors)
        known_ids_str = ", ".join(known_ids)
        added = 0

        for c in empty:
            prompt = f"""Connector `{c.connector_id}` has NO wires connected to it in the current extraction.
What wires connect to `{c.connector_id}`? Please extract them from the attached diagram.

Valid connector_ids: {known_ids_str}

Return ONLY a JSON array of Wire objects:
```json
[
  {{
    "wire_id": "<part_name>",
    "source_connector_id": "<valid_id>",
    "source_pin_number": <pin>,
    "destination_connector_id": "<valid_id>",
    "destination_pin_number": <pin>,
    "color": "unknown"
  }}
]
```
If there really are no wires, return `[]`.
/no_think"""
            try:
                self._current_phase = "heal_empty_conn"
                self._current_batch = 0
                response = self.vlm.query(
                    prompt,
                    image_data=self.page_images[0],
                    log_turn=True,
                )
                self._log_vlm("heal_empty_conn", 0, prompt, response)

                if isinstance(response, list):
                    valid = self._validate_wire_batch(response)
                    if valid:
                        self.accumulated_wires.extend(valid)
                        added += len(valid)
                        logger.info(f"    empty connector {c.connector_id}: added {len(valid)} wires")
            except Exception as e:
                logger.warning(f"    Failed to heal empty connector {c.connector_id}: {e}")

        return added

    # ------------------------------------------------------------------
    # Scan helpers for _all_detectors_clean
    # ------------------------------------------------------------------

    def _all_detectors_clean(self) -> bool:
        """Returns True iff every detector scan returns empty."""
        # Duplicates?
        seen = set()
        for w in self.accumulated_wires:
            key = (w.wire_id, w.source_connector_id, w.source_pin_number,
                   w.destination_connector_id, w.destination_pin_number)
            if key in seen:
                return False
            seen.add(key)

        # Spurious wires?
        bom_names = set(self._bom_wire_part_number.keys())
        if bom_names:
            for w in self.accumulated_wires:
                if w.wire_id not in bom_names:
                    return False

        # Orphans?
        known_ids = {c.connector_id for c in self.accumulated_connectors}
        for w in self.accumulated_wires:
            if w.source_connector_id not in known_ids:
                return False
            if w.destination_connector_id not in known_ids:
                return False

        # Pin conflicts?
        pin_occupancy = {}
        for w in self.accumulated_wires:
            src_key = (w.source_connector_id, w.source_pin_number)
            dst_key = (w.destination_connector_id, w.destination_pin_number)
            if src_key[0] and src_key[1]:
                pin_occupancy.setdefault(src_key, []).append(w)
            if dst_key[0] and dst_key[1]:
                pin_occupancy.setdefault(dst_key, []).append(w)
        for wires_list in pin_occupancy.values():
            if len(wires_list) > 1:
                return False

        # Empty connectors?
        connected_cids = set()
        for w in self.accumulated_wires:
            if w.source_connector_id:
                connected_cids.add(w.source_connector_id)
            if w.destination_connector_id:
                connected_cids.add(w.destination_connector_id)
        for c in self.accumulated_connectors:
            if c.connector_id not in connected_cids:
                return False

        return True

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    def _validate_connector_batch(self, data):
        """Validate and parse connector batch."""
        if isinstance(data, dict):
            data = [data]
        valid = []
        for item in data:
            try:
                c = Connector(**item)
                valid.append(c)
            except ValidationError as e:
                logger.warning(f"Invalid connector: {e}")
        return valid
    
    # Maps the color suffix in BOM part_number (e.g. FLRY-0.35-RD) to a
    # WireColor enum value. Kept here (not imported from eval/) so the
    # extractor stays independent of the eval package.
    _PART_NUMBER_COLOR_CODES = {
        "RD": "red", "RT": "red",
        "BU": "blue", "BL": "blue",
        "GN": "green",
        "YE": "yellow", "GE": "yellow",
        "BK": "black", "SW": "black",
        "WH": "white", "WS": "white",
        "OG": "orange",
        "BR": "brown",
        "GY": "gray", "GR": "gray",
    }


    @staticmethod
    def _color_from_part_number(part_number: Optional[str]) -> Optional[str]:
        """Decode the trailing IEC color code from a wire part_number."""
        if not part_number:
            return None
        suffix = part_number.strip().split("-")[-1].upper()
        return WiringDiagramExtractor._PART_NUMBER_COLOR_CODES.get(suffix)

    def _validate_wire_batch(self, data):
        """Validate and parse wire batch; backfill part_number + sanity-check color."""
        if isinstance(data, dict):
            data = [data]
        valid = []
        for item in data:
            try:
                w = Wire(**item)
            except ValidationError as e:
                logger.warning(f"Invalid wire: {e}")
                continue

            # Backfill part_number from BOM lookup (wire_id → part_name → part_number).
            if not w.part_number:
                w.part_number = self._bom_wire_part_number.get(w.wire_id)

            # If BOM part_number encodes a color and the VLM got it wrong,
            # trust the BOM. This is a cheap post-extraction validation.
            bom_color = self._color_from_part_number(w.part_number)
            if bom_color and w.color.value != bom_color:
                logger.debug(f"    Color fix for {w.wire_id}: {w.color.value} -> {bom_color}")
                try:
                    from parsing.util.structure import WireColor
                except ImportError:
                    from util.structure import WireColor
                w.color = WireColor(bom_color)

            valid.append(w)
        return valid
    
    def _assemble_diagram(self) -> WiringDiagram:
        """Assemble final WiringDiagram."""
        return WiringDiagram(
            diagram_id="PLACE-HOLDER-PLACE-HOLDER",
            diagram_name="Extracted Wiring Diagram",
            connectors=self.accumulated_connectors,
            wires=self.accumulated_wires,
            wire_groups=[]
        )
    
    def _save_output(self, diagram):
        """Save to JSON file."""
        try:
            with open(self.output_path, 'w') as f:
                json.dump(diagram.model_dump(), f, indent=2, default=str)
            logger.info(f"Saved to {self.output_path}")
        except Exception as e:
            logger.error(f"Failed to save: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract wiring diagram from PDF using VLM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s diagram.pdf
  %(prog)s diagram.pdf --csv bom.csv
  %(prog)s diagram.pdf -o extracted.json --verbose
        """
    )
    
    parser.add_argument("pdf_path", help="Path to input PDF file")
    parser.add_argument("--csv", dest="csv_path", default=None,
                       help="Path to BOM CSV file (semicolon-separated)")
    parser.add_argument("--output", "-o", default=None,
                       help="Output JSON path (default: <pdf_name>.json)")
    parser.add_argument("--host", "-H", default="http://localhost:12345",
                       help="VLM API host (default: http://localhost:12345)")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="Enable verbose logging")
    
    args = parser.parse_args()
    
    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level, format="%(asctime)s [%(levelname)s] %(message)s")
    logger = logging.getLogger(__name__)
    
    # Validate PDF exists
    if not os.path.exists(args.pdf_path):
        logger.error(f"PDF not found: {args.pdf_path}")
        sys.exit(1)
    
    # Create extractor
    extractor = WiringDiagramExtractor(
        pdf_path=args.pdf_path,
        csv_path=args.csv_path,
        output_path=args.output,
        vlm_url=args.host,
        verbose=args.verbose
    )
    
    try:
        diagram = extractor.extract()
        
        logger.info(f"Extraction successful!")
        logger.info(f"  Connectors: {len(diagram.connectors)}")
        logger.info(f"  Wires: {len(diagram.wires)}")
        logger.info(f"  Output: {args.output or '(memory)'}")
        
        # Print summary
        if args.verbose:
            print("\n=== Summary ===")
            print(f"Connectors: {len(diagram.connectors)}")
            for c in diagram.connectors:
                print(f"  - {c.connector_id}: {c.connector_name} ({c.pin_count} pins)")
            print(f"Wires: {len(diagram.wires)}")
            for w in diagram.wires[:10]:
                print(f"  - {w.wire_id}: {w.source_connector_id}:{w.source_pin_number} -> "
                      f"{w.destination_connector_id}:{w.destination_pin_number} ({w.color})")
            if len(diagram.wires) > 10:
                print(f"  ... and {len(diagram.wires) - 10} more")
        
    except Exception as e:
        logger.error(f"Extraction failed: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)
