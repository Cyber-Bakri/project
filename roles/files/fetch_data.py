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
    """Calculate the date range for compliance data filtering"""
    present_date = datetime.now()
    start_date = present_date - timedelta(days=90)
    end_date = present_date
    
    start_date_str = start_date.strftime("%Y-%m-%dT00:00:00Z")
    end_date_str = end_date.strftime("%Y-%m-%dT23:59:59Z")
    
    return start_date_str, end_date_str

def query_elasticsearch():
    """Query Elasticsearch using environment variables for configuration"""
    
    # Get environment variables
    es_host = get_env_var("ES_HOST", required=True)
    es_index = get_env_var("ES_INDEX", required=True)
    issue_type = get_env_var("ISSUE_TYPE", "")  # Current issue type being processed
    
    # Get date range for filtering
    start_date, end_date = get_date_range()
    print(f"Fetching data from {start_date} to {end_date}")
    if issue_type:
        print(f"Filtering for issue type: {issue_type}")
    
    # Get authentication if provided
    username = get_env_var("ES_USERNAME", "")
    password = get_env_var("ES_PASSWORD", "")
    auth = None
    if username and password:
        auth = (username, password)
    
    # Build the search URL
    search_url = f"{es_host}/{es_index}/_search"
    
    # Build the query with proper filtering
    must_filters = [
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
    
    # Add issue type filter if specified
    if issue_type:
        must_filters.append({
            "term": {
                "issueType.keyword": issue_type
            }
        })
    
    timestamp_fields = ["@timestamp", "timestamp", "createdDate", "detectedDate", "lastSeen"]
    
    # For now, let's use a configurable timestamp field or skip if not available
    timestamp_field = get_env_var("TIMESTAMP_FIELD", "")
    if timestamp_field:
        must_filters.append({
            "range": {
                timestamp_field: {
                    "gte": start_date,
                    "lte": end_date
                }
            }
        })
        print(f"Applied date filter on field: {timestamp_field}")
    else:
        print("No timestamp field specified - fetching all available data")
    
    # Prepare the query
    query = {
        "_source": ["issueType", "appCode", "severity", "affectedItemType", "affectedItemName", 
                   "issueName", "complianceAssetId", "contact-info", "@timestamp", "timestamp"],
        "query": {
            "bool": {
                "must": must_filters
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
                            "field": "issueType.keyword",
                            "size": 50
                        }
                    }
                }
            },
            "all_issue_types": {
                "terms": {
                    "field": "issueType.keyword",
                    "size": 50
                }
            }
        },
        "size": 1000,  # Get actual documents
        "sort": [{"_score": {"order": "desc"}}]
    }
    
    headers = {
        "Content-Type": "application/json"
    }
    
    try:
        print(f"Querying Elasticsearch at: {search_url}")
        response = requests.post(
            search_url,
            headers=headers,
            json=query,
            auth=auth,
            verify=False,
            timeout=30
        )
        
        print(f"Response status code: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            
            hits = result.get("hits", {}).get("hits", [])
            total = result.get("hits", {}).get("total", {})
            if isinstance(total, dict):
                total_count = total.get("value", 0)
            else:
                total_count = total
            
            print(f"Total documents found: {total_count}")
            print(f"Retrieved {len(hits)} documents")
            
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
            
            result["query_metadata"] = {
                "date_range": {
                    "start_date": start_date,
                    "end_date": end_date
                },
                "issue_type_filter": issue_type,
                "timestamp_field_used": timestamp_field,
                "query_timestamp": datetime.now().isoformat()
            }
            
            output_file = get_env_var("OUTPUT_FILE", "")
            if output_file:
                os.makedirs(os.path.dirname(output_file) if os.path.dirname(output_file) else ".", exist_ok=True)
                
                with open(output_file, 'w') as f:
                    json.dump(result, f, indent=2)
                print(f"Query results saved to {output_file}")
            
            print(f"Found {len(app_codes_with_issues)} app codes with issues")
            print(f"Total issue types found: {len(all_issue_types)}")
            if all_issue_types:
                print(f"Issue types: {', '.join(sorted(all_issue_types))}")
            
            if hits:
                print("Sample document structure:")
                sample_source = hits[0].get("_source", {})
                print(f"Available fields: {list(sample_source.keys())}")
                
                # Show app codes in sample
                app_codes_in_sample = [doc.get("_source", {}).get("appCode") for doc in hits[:5]]
                app_codes_in_sample = [ac for ac in app_codes_in_sample if ac]
                if app_codes_in_sample:
                    print(f"Sample app codes: {', '.join(app_codes_in_sample)}")
            else:
                print("No documents returned in hits, but continuing with aggregation data")
            
            return True
            
        else:
            print(f"ERROR: Elasticsearch returned status code {response.status_code}")
            print(f"Response: {response.text}")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"ERROR: Network/Request error: {str(e)}")
        return False
    except Exception as e:
        print(f"ERROR: Failed to query Elasticsearch: {str(e)}")
        return False
    finally:
        output_file = get_env_var("OUTPUT_FILE", "")
        if output_file and not os.path.exists(output_file):
            empty_result = {
                "hits": {
                    "hits": [], 
                    "total": {"value": 0}
                },
                "aggregations": {
                    "by_app_code": {"buckets": []},
                    "all_issue_types": {"buckets": []}
                },
                "query_metadata": {
                    "date_range": {
                        "start_date": get_date_range()[0],
                        "end_date": get_date_range()[1]
                    },
                    "issue_type_filter": get_env_var("ISSUE_TYPE", ""),
                    "timestamp_field_used": get_env_var("TIMESTAMP_FIELD", ""),
                    "query_timestamp": datetime.now().isoformat(),
                    "status": "empty_result_created"
                }
            }
            try:
                os.makedirs(os.path.dirname(output_file) if os.path.dirname(output_file) else ".", exist_ok=True)
                with open(output_file, 'w') as f:
                    json.dump(empty_result, f, indent=2)
                print(f"Created empty result file at {output_file}")
            except Exception as file_error:
                print(f"Failed to create output file: {file_error}")

if __name__ == "__main__":
    success = query_elasticsearch()
    sys.exit(0) 
