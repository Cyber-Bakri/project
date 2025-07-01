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
    """Query Elasticsearch using environment variables for configuration"""
    
    # Get environment variables
    es_host = get_env_var("ES_HOST", required=True)
    es_index = get_env_var("ES_INDEX", required=True)
    
    # date range for last week
    start_date, end_date = get_date_range()
    print(f"Fetching data from {start_date} to {end_date}")
    
    # Get authentication if provided
    username = get_env_var("ES_USERNAME", "")
    password = get_env_var("ES_PASSWORD", "")
    auth = None
    if username and password:
        auth = (username, password)
    
    # Build the search URL
    search_url = f"{es_host}/{es_index}/_search"
    
    # Prepare the query - simplified to match actual data structure
    query = {
        "query": {
            "bool": {
                "must": [
                    {
                        "exists": {
                            "field": "issueType"
                        }
                    },
                    {
                        "exists": {
                            "field": "appCode"
                        }
                    }
                ]
                # Removed priority and issueState filters as they may not exist in actual data
                # Add date range filter if needed:
                # {
                #     "range": {
                #         "timestamp": {
                #             "gte": start_date,
                #             "lte": end_date
                #         }
                #     }
                # }
            }
        },
        "aggs": {
            "by_app_code": {
                "terms": {
                    "field": "appCode.keyword",
                    "size": 1000
                },
                "aggs": {
                    "issue_types": {
                        "terms": {
                            "field": "issueType.keyword"
                        }
                    }
                }
            },
            "all_issue_types": {
                "terms": {
                    "field": "issueType.keyword"
                }
            }
        },
        "size": 1000  # Increase size to get more actual documents
    }
    
    headers = {
        "Content-Type": "application/json"
    }
    
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
            
            app_codes_with_issues = []
            all_issue_types = set()
            
            if "aggregations" in result:
                if "all_issue_types" in result["aggregations"]:
                    for bucket in result["aggregations"]["all_issue_types"]["buckets"]:
                        all_issue_types.add(bucket["key"])
                
                if "by_app_code" in result["aggregations"]:
                    for app_bucket in result["aggregations"]["by_app_code"]["buckets"]:
                        if app_bucket["doc_count"] > 0:
                            app_code = app_bucket["key"]
                            app_issue_types = []
                            
                            if "issue_types" in app_bucket:
                                for type_bucket in app_bucket["issue_types"]["buckets"]:
                                    app_issue_types.append(type_bucket["key"])
                            
                            app_codes_with_issues.append({
                                "app_code": app_code,
                                "issue_types": app_issue_types,
                                "count": app_bucket["doc_count"]
                            })
            
            output_file = get_env_var("OUTPUT_FILE", "")
            if output_file:
                result["date_range"] = {
                    "start_date": start_date,
                    "end_date": end_date
                }
                
                with open(output_file, 'w') as f:
                    json.dump(result, f, indent=2)
                print(f"Query results saved to {output_file}")
                print(f"Found {len(app_codes_with_issues)} app codes with issues")
                print(f"Total issue types found: {len(all_issue_types)}")
                print(f"Issue types: {', '.join(sorted(all_issue_types))}")
                
                # Print sample of actual documents for debugging
                hits = result.get("hits", {}).get("hits", [])
                total = result.get("hits", {}).get("total", {}).get("value", 0)
                print(f"Total documents: {total}")
                print(f"Retrieved {len(hits)} documents")
                
                if hits:
                    print("Sample document structure:")
                    sample_source = hits[0].get("_source", {})
                    print(f"Available fields: {list(sample_source.keys())}")
                else:
                    print("No documents returned, but continuing with empty result set")
        else:
            hits = result.get("hits", {}).get("hits", [])
            total = result.get("hits", {}).get("total", {}).get("value", 0)
            print(f"Query returned {total} results across {len(app_codes_with_issues)} app codes")
        
        return True
    except Exception as e:
        print(f"ERROR: Failed to query Elasticsearch: {str(e)}")
        
        # Still create an empty output file to avoid failing the pipeline
        output_file = get_env_var("OUTPUT_FILE", "")
        if output_file:
            empty_result = {
                "hits": {"hits": [], "total": {"value": 0}},
                "aggregations": {},
                "error": str(e),
                "date_range": {
                    "start_date": get_date_range()[0],
                    "end_date": get_date_range()[1]
                }
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
    sys.exit(0 if success else 1) 
