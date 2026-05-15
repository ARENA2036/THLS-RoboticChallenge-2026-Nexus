import json
import sqlite3
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse
import asyncio

import os
import sys
import datetime
import shutil

from typing import List
from fastapi import File

# Add the project root to the python path so 'public' can be found
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

from public.cdm.definitions.cdm_schema import WireHarness

from harness_builder.backend.parsing.parsers import KBLImporter, SchemaImporter
from harness_builder.backend.quoting.enrich_cdm_from_digikey import enrich_harness

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_FILE = "harness.db"


def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS harness_store (
            id INTEGER PRIMARY KEY DEFAULT 1,
            data TEXT NOT NULL
        )
    ''')

    conn.commit()
    conn.close()


@app.on_event("startup")
def on_startup():
    init_db()


HARNESS_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "wire_harness.json")

@app.get("/harness")
def get_harness():
    try:
        if not os.path.exists(HARNESS_FILE):
            # Try to fall back to DB if file missing
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("SELECT data FROM harness_store WHERE id = 1")
            row = c.fetchone()
            conn.close()
            if row:
                return JSONResponse(content=json.loads(row["data"]))
            raise HTTPException(status_code=404, detail="No harness data found")
        
        with open(HARNESS_FILE, 'r') as f:
            data = json.load(f)
        return JSONResponse(content=data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _store_harness_json(data: dict):
    """Store harness JSON data in the wire_harness.json file."""
    try:
        with open(HARNESS_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        
        # Also sync to DB for backward compatibility/internal tracking
        conn = get_db_connection()
        c = conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO harness_store (id, data) VALUES (1, ?)",
            (json.dumps(data),)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error storing harness: {e}")


@app.post("/parse")
async def process_pipeline(files: List[UploadFile] = File(...)):
    """
    Unified 3-step processing pipeline with SSE feedback using a Queue.
    """
    queue = asyncio.Queue()

    async def event_generator():
        while True:
            event = await queue.get()
            if event is None: # Sentinel for completion
                break
            yield event

    async def run_pipeline():
        # Create archive directory
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = os.path.join(os.path.dirname(__file__), "..", "..", "archives", f"run_{timestamp}")
        inputs_dir = os.path.join(run_dir, "inputs")
        os.makedirs(inputs_dir, exist_ok=True)
        
        harness_dict_result = None

        try:
            kbl_files = []
            visual_files = []

            # Save uploaded files to archive and sort them
            for file in files:
                ext = file.filename.lower().split('.')[-1]
                file_path = os.path.join(inputs_dir, file.filename)
                
                # Write file to archive
                content = await file.read()
                with open(file_path, "wb") as f:
                    f.write(content)
                # Reset file pointer for subsequent reads in the pipeline
                await file.seek(0)

                if ext in ['kbl', 'xml']:
                    kbl_files.append(file)
                elif ext in ['pdf', 'png', 'jpg', 'jpeg', 'tif', 'tiff']:
                    visual_files.append(file)
                    
            if not kbl_files:
                await queue.put({
                    "event": "error",
                    "data": json.dumps({"detail": "Pipeline requires at least one KBL/XML file as a baseline."})
                })
                await queue.put(None)
                return

            async def send_progress(title: str, subtitle: str, counter: int = None):
                payload = {"title": title, "subtitle": subtitle}
                if counter is not None:
                    payload["counter"] = counter
                await queue.put({
                    "event": "progress",
                    "data": json.dumps(payload)
                })
                # Small sleep to yield to the event generator
                await asyncio.sleep(0.01)

            # --- Step 1: Initial Parsing (KBL) ---
            await send_progress("KBL", f"Parsing baseline KBL ({kbl_files[0].filename})")
            kbl_content = await kbl_files[0].read()
            try:
                harness = KBLImporter().parse(kbl_content, kbl_files[0].filename)
            except Exception as e:
                await queue.put({
                    "event": "error",
                    "data": json.dumps({"detail": f"Failed to parse KBL: {str(e)}"})
                })
                await queue.put(None)
                return

            # --- Step 2: Component Enrichment (DigiKey) ---
            await send_progress("DIGIKEY", "Enriching components via DigiKey API")
            try:
                # Run enrichment in a thread pool since it's synchronous IO-bound
                loop = asyncio.get_event_loop()
                harness = await loop.run_in_executor(None, lambda: enrich_harness(harness, limit=50))
            except Exception as e:
                await send_progress("DIGIKEY", f"Enrichment Error: {str(e)}")
                pass

            # --- Step 3: Visual Enrichment (PDF/Images) ---
            if visual_files:
                await send_progress("Image enrichment", f"Preparing {len(visual_files)} files for OCR")
                schema_importer = SchemaImporter()
                v_files_data = []
                for v_file in visual_files:
                    v_content = await v_file.read()
                    v_files_data.append((v_file.filename, v_content))
                    
                try:
                    async def progress_callback(title, subtitle, counter=None):
                        await send_progress(title, subtitle, counter)

                    harness_dict = await schema_importer.parse(v_files_data, existing_harness=harness, progress_callback=progress_callback)
                    
                    if isinstance(harness_dict, dict):
                        harness_dict_result = harness_dict
                    else:
                        harness_dict_result = harness_dict.model_dump()
                except Exception as e:
                    await send_progress("Image enrichment", f"Failed to process visual files: {str(e)}")
                    harness_dict_result = harness.model_dump()
            else:
                await send_progress("Image enrichment", "Skipped (no visual files)")
                harness_dict_result = harness.model_dump()

            # finalize
            _store_harness_json(harness_dict_result)
            
            # Save final result to archive
            with open(os.path.join(run_dir, "wire_harness.json"), "w") as f:
                json.dump(harness_dict_result, f, indent=2)

            await send_progress("Complete", "Parsing finished successfully")
            await queue.put({
                "event": "result",
                "data": json.dumps(harness_dict_result)
            })
        except Exception as e:
            await queue.put({
                "event": "error",
                "data": json.dumps({"detail": f"Pipeline internal error: {str(e)}"})
            })
        finally:
            # Copy log to archive folder
            log_path = os.path.join(os.path.dirname(__file__), "vlm_parsing.log")
            if os.path.exists(log_path):
                shutil.copy(log_path, os.path.join(run_dir, "vlm_parsing.log"))
            
            await queue.put(None)

    # Start the pipeline in the background
    asyncio.create_task(run_pipeline())

    return EventSourceResponse(event_generator())

@app.put("/harness")
async def update_harness(harness: WireHarness):
    harness_dict = harness.model_dump()
    _store_harness_json(harness_dict)
    return JSONResponse(content=harness_dict)
