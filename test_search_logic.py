import sys
import os

# Add current directory to path
sys.path.append(os.getcwd())

from search_query import QueryParser, QueryMatcher

def test_logic():
    print("🧪 Testing Boolean Search Logic...")
    
    cases = [
        {
            "query": "iran AND israel",
            "regex": False,
            "text": "Will Iran strike Israel by March?",
            "expected": True
        },
        {
            "query": "iran AND israel",
            "regex": False,
            "text": "Iran launches attack",
            "expected": False
        },
        {
            "query": "iran OR israel",
            "regex": False,
            "text": "Israel defense system active",
            "expected": True
        },
        {
            "query": "iran EXCLUDE USA",
            "regex": False,
            "text": "Iran and USA relations",
            "expected": False
        },
        {
            "query": "iran EXCLUDE USA",
            "regex": False,
            "text": "Iran domestic policy",
            "expected": True
        },
        {
            "query": "(iran OR israel) EXCLUDE USA",
            "regex": False,
            "text": "Israel vs Iran conflict",
            "expected": True
        },
        {
            "query": "(iran OR israel) EXCLUDE USA",
            "regex": False,
            "text": "USA mediates Israel Iran conflict",
            "expected": False
        },
        {
            "query": "iran",
            "regex": True,
            "text": "The Iranian government announced...",
            "expected": True
        },
         {
            "query": "iran",
            "regex": True,
            "text": "Iran's response to the event",
            "expected": True
        }
    ]
    
    passed = 0
    for i, case in enumerate(cases):
        try:
            root = QueryParser.parse(case["query"])
            matcher = QueryMatcher(root, case["query"], use_regex=case["regex"])
            result = matcher.matches(case["text"])
            
            if result == case["expected"]:
                print(f"✅ Test {i+1} Passed: '{case['query']}' vs '{case['text']}' (Regex: {case['regex']})")
                passed += 1
            else:
                print(f"❌ Test {i+1} Failed: '{case['query']}' vs '{case['text']}' (Regex: {case['regex']})")
                print(f"   Expected {case['expected']}, got {result}")
        except Exception as e:
            print(f"💥 Test {i+1} Error: {e}")
            
    print(f"\n📊 Results: {passed}/{len(cases)} passed")

if __name__ == "__main__":
    test_logic()
