"""
search_query.py
Query parsing and matching logic for Polymarket event filtering.
Supports Boolean logic: AND, OR, EXCLUDE and grouping ().
"""

import re
from typing import List, Union, Optional

class QueryNode:
    """Base class for query expression tree nodes"""
    def matches(self, text: str, use_regex: bool) -> bool:
        raise NotImplementedError

class TermNode(QueryNode):
    def __init__(self, term: str):
        self.term = term.strip().lower()
        # Pre-compile regex for performance if needed
        self._regex_pattern = None

    def matches(self, text: str, use_regex: bool) -> bool:
        text_lower = text.lower()
        if not use_regex:
            return self.term in text_lower
        
        # IMPROVEMENT: Match word variants (e.g., "iran" matches "iranian", "iran's")
        # We use \b and \w* to allow trailing characters
        if not self._regex_pattern:
            # Escape to be safe, then allow word characters to follow
            pattern = r'\b' + re.escape(self.term) + r'\w*'
            self._regex_pattern = re.compile(pattern, re.IGNORECASE)
            
        return bool(self._regex_pattern.search(text))

class AndNode(QueryNode):
    def __init__(self, left: QueryNode, right: QueryNode):
        self.left = left
        self.right = right

    def matches(self, text: str, use_regex: bool) -> bool:
        return self.left.matches(text, use_regex) and self.right.matches(text, use_regex)

class OrNode(QueryNode):
    def __init__(self, left: QueryNode, right: QueryNode):
        self.left = left
        self.right = right

    def matches(self, text: str, use_regex: bool) -> bool:
        return self.left.matches(text, use_regex) or self.right.matches(text, use_regex)

class ExcludeNode(QueryNode):
    def __init__(self, left: QueryNode, right: QueryNode):
        self.left = left
        self.right = right

    def matches(self, text: str, use_regex: bool) -> bool:
        # Matches if left matches AND right does NOT match
        return self.left.matches(text, use_regex) and not self.right.matches(text, use_regex)

class QueryParser:
    """Parses user input into a Boolean expression tree"""
    
    @staticmethod
    def parse(user_input: str) -> QueryNode:
        """
        Parse user query string into a QueryNode tree
        
        Logic supported:
        - term1 AND term2 (capitalized)
        - term1 OR term2 (capitalized)
        - term1 EXCLUDE term2 (capitalized)
        - parentheses for grouping ( )
        """
        if not user_input or not user_input.strip():
            raise ValueError("Query cannot be empty")
            
        tokens = QueryParser._tokenize(user_input)
        node, remaining = QueryParser._parse_expression(tokens)
        
        if remaining:
            raise ValueError(f"Unexpected tokens after query: {' '.join(remaining)}")
            
        return node

    @staticmethod
    def _tokenize(user_input: str) -> List[str]:
        # Handle parentheses and operators
        # We want to split but keep the tokens
        user_input = user_input.replace('(', ' ( ').replace(')', ' ) ')
        # Special handling for EXCLUDE to treat it as a single token
        # (Already handled by split if it has spaces around it)
        return user_input.split()

    @staticmethod
    def _parse_expression(tokens: List[str]) -> (QueryNode, List[str]):
        """Parse OR logic (lowest precedence)"""
        left, tokens = QueryParser._parse_and(tokens)
        
        while tokens and tokens[0] == 'OR':
            op = tokens[0]
            right, tokens = QueryParser._parse_and(tokens[1:])
            left = OrNode(left, right)
            
        return left, tokens

    @staticmethod
    def _parse_and(tokens: List[str]) -> (QueryNode, List[str]):
        """Parse AND and EXCLUDE logic (medium precedence)"""
        left, tokens = QueryParser._parse_primary(tokens)
        
        while tokens and tokens[0] in ('AND', 'EXCLUDE'):
            op = tokens[0]
            right, tokens = QueryParser._parse_primary(tokens[1:])
            if op == 'AND':
                left = AndNode(left, right)
            else: # EXCLUDE
                left = ExcludeNode(left, right)
                
        return left, tokens

    @staticmethod
    def _parse_primary(tokens: List[str]) -> (QueryNode, List[str]):
        """Parse terms and parentheses (highest precedence)"""
        if not tokens:
            raise ValueError("Unexpected end of query")
            
        token = tokens[0]
        
        if token == '(':
            node, remaining = QueryParser._parse_expression(tokens[1:])
            if not remaining or remaining[0] != ')':
                raise ValueError("Unclosed parenthesis")
            return node, remaining[1:]
        
        if token in ('AND', 'OR', 'EXCLUDE', ')'):
            raise ValueError(f"Unexpected operator or parenthesis: {token}")
            
        return TermNode(token), tokens[1:]


class QueryMatcher:
    """Matches text against query logic using the expression tree"""
    
    def __init__(self, root_node: QueryNode, raw_query: str, use_regex: bool = False):
        """
        Initialize matcher
        
        Args:
            root_node: The root of the expression tree from QueryParser.parse()
            raw_query: The original query string for display
            use_regex: Whether to use regex matching for terms
        """
        self.root = root_node
        self.raw = raw_query
        self.use_regex = use_regex
    
    def matches(self, text: str) -> bool:
        """Check if text matches the query logic"""
        if not text:
            return False
        return self.root.matches(text, self.use_regex)
    
    def get_display_query(self) -> str:
        """Get human-readable query string"""
        regex_status = " (REGEX ON)" if self.use_regex else ""
        return f"Query: {self.raw}{regex_status}"
