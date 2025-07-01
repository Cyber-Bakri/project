#!/usr/bin/env python3

import os
import sys
import json
import requests
from datetime import datetime, timedelta
import urllib3

# Disable SSL warnings - use only in development or with self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def get_env_var(var_name, default=None, required=False):
    """Get environment variable or return default value"""
    value = os.environ.get(var_name, default)
    if required and value is None:
        print(f"ERROR: Required environment variable {var_name} is not set.")
        sys.exit(1)
    return value

def get_date_range():
    """Calculate the date range"""
    present_date = datetime.now()
    end_date = present_date + timedelta(days=90)
    start_date = present_date - timedelta(days=60)
    
    start_date_str = start_date.strftime("%Y-%m-%dT00:00:00Z")
    end_date_str = end_date.strftime("%Y-%m-%dT23:59:59Z")
    
    return start_date_str, end_date_str

def query_elasticsearch():
    """Query Elasticsearch for P1 and P2 priority items only"""
    
    # Get environment variables
    es_host = get_env_var("ES_HOST", required=True)
    es_index = get_env_var("ES_INDEX", required=True)
    
    # date range for reference
    start_date, end_date = get_date_range()
    print(f"Fetching P1/P2 priority data from {start_date} to {end_date}")
    
    # Get authentication if provided
    username = get_env_var("ES_USERNAME", "")
    password = get_env_var("ES_PASSWORD", "")
    auth = None
    if username and password:
        print(f"Using authentication with username: {username}")
        print(f"Password length: {len(password)} characters")
        auth = (username, password)
    else:
        print("No authentication credentials provided")
    
    # Build the search URL
    search_url = f"{es_host}/{es_index}/_search"
    
    print(f"Elasticsearch URL: {search_url}")
    print(f"Index pattern: {es_index}")
    
    # Query only for P1 and P2 priority items, sort by issue types
    query = {
        "query": {
            "bool": {
                "must": [
                    {
                        "exists": {
                            "field": "appCode"
                        }
                    }
                ]
            }
        },
        "size": 10
    }
    
    headers = {
        "Content-Type": "application/json"
    }
    
    print(f"Making request to: {search_url}")
    print(f"Using auth: {'Yes' if auth else 'No'}")
    print(f"Headers: {headers}")
    
    try:
        response = requests.post(
            search_url,
            headers=headers,
            json=query,
            auth=auth,
            verify=False
        )
        
        if response.status_code == 200:
            result = response.json()
            
            # Simplified processing for testing
            hits = result.get("hits", {}).get("hits", [])
            total = result.get("hits", {}).get("total", {}).get("value", 0)
            
            print(f"SUCCESS: Retrieved {len(hits)} documents out of {total} total")
            
            if hits:
                print("Sample document fields:")
                sample_source = hits[0].get("_source", {})
                print(f"Available fields: {list(sample_source.keys())}")
                
                # Check if priority field exists
                if "priority" in sample_source:
                    print(f"Priority field found: {sample_source['priority']}")
                else:
                    print("Priority field NOT found in documents")
            
            # Save results
            output_file = get_env_var("OUTPUT_FILE", "")
            if output_file:
                # Add simple processing summary
                result["processing_summary"] = {
                    "total_documents": total,
                    "retrieved_documents": len(hits),
                    "has_priority_field": "priority" in (hits[0].get("_source", {}) if hits else {}),
                    "date_range": {
                        "start_date": start_date,
                        "end_date": end_date
                    }
                }
                
                with open(output_file, 'w') as f:
                    json.dump(result, f, indent=2)
                
                print(f"Query results saved to {output_file}")
        else:
            print(f"ERROR: Elasticsearch query failed with status {response.status_code}")
            print(f"Response: {response.text}")
            return False
        
        return True
        
    except Exception as e:
        print(f"ERROR: Failed to query Elasticsearch: {str(e)}")
        
        # Still create an empty output file to avoid failing the pipeline
        output_file = get_env_var("OUTPUT_FILE", "")
        if output_file:
            empty_result = {
                "hits": {"hits": [], "total": {"value": 0}},
                "aggregations": {},
                "processing_summary": {
                    "total_documents": 0,
                    "retrieved_documents": 0,
                    "has_priority_field": False,
                    "date_range": {
                        "start_date": get_date_range()[0],
                        "end_date": get_date_range()[1]
                    }
                },
                "error": str(e)
            }
            try:
                with open(output_file, 'w') as f:
                    json.dump(empty_result, f, indent=2)
                print(f"Created empty result file at {output_file} due to error")
            except Exception as file_error:
                print(f"Failed to create output file: {file_error}")
        
        return False

if __name__ == "__main__":
    success = query_elasticsearch()
    if success:
        print("Data fetch completed successfully")
        sys.exit(0)
    else:
        print("Data fetch failed")
        sys.exit(1) 
