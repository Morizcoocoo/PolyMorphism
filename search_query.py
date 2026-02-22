"""
search_query.py
Query parsing and matching logic for Polymarket event filtering
"""

class QueryParser:
    """Parses user input into structured query objects"""
    
    @staticmethod
    def parse(user_input: str) -> dict:
        """
        Parse user query into structured format
        
        Args:
            user_input: Raw string from user
            
        Returns:
            dict with 'type', 'terms', 'raw'
        """
        user_input = user_input.strip().lower()
        
        if not user_input:
            raise ValueError("Query cannot be empty")
        
        # Ordered phrase (hyphen-separated)
        if "-" in user_input:
            terms = [term.strip() for term in user_input.split("-")]
            return {
                'type': 'ordered',
                'terms': terms,
                'raw': user_input
            }
        
        # Unordered multi-term (comma-separated)
        elif "," in user_input:
            terms = [term.strip() for term in user_input.split(",")]
            return {
                'type': 'unordered',
                'terms': terms,
                'raw': user_input
            }
        
        # Single keyword
        else:
            return {
                'type': 'single',
                'terms': [user_input],
                'raw': user_input
            }


class QueryMatcher:
    """Matches text against query logic"""
    
    def __init__(self, query_config: dict):
        """
        Initialize matcher with parsed query
        
        Args:
            query_config: Output from QueryParser.parse()
        """
        self.query_type = query_config['type']
        self.terms = query_config['terms']
        self.raw = query_config['raw']
    
    def matches(self, text: str) -> bool:
        """
        Check if text matches the query
        
        Args:
            text: Text to match against (e.g., market title)
            
        Returns:
            True if matches query logic
        """
        if not text:
            return False
        
        text_lower = text.lower()
        
        if self.query_type == 'single':
            return self.terms[0] in text_lower
        
        elif self.query_type == 'unordered':
            # ALL terms must appear (any order)
            return all(term in text_lower for term in self.terms)
        
        elif self.query_type == 'ordered':
            # Terms must appear in exact sequence
            pattern = "-".join(self.terms)
            return pattern in text_lower
        
        return False
    
    def get_display_query(self) -> str:
        """Get human-readable query string"""
        if self.query_type == 'single':
            return f'"{self.terms[0]}"'
        elif self.query_type == 'unordered':
            return f'All of: {", ".join(self.terms)}'
        else:  # ordered
            return f'Phrase: "{"-".join(self.terms)}"'
