# ORS Manual — Drop Your PDF Here

Place the BLS ORS Field Economist Collection Manual PDF in this folder and
name it exactly:

    ors_collection_manual.pdf

Then run the one-time setup script to upload it to watsonx.ai and create
the vector index:

    venv/bin/python tools/gsa_pkr_toolkit/ors_knowledge_base.py

The script will print the resulting VECTOR_INDEX_ID. Copy that value into
your .env file:

    ORS_VECTOR_INDEX_ID=<the-id-printed-by-the-script>

Once that is set, the search_ors_manual MCP tool and the LLM extraction
pipeline will automatically retrieve relevant manual sections before
calling Granite.
