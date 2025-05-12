import os
import pyodbc
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Azure OpenAI
from langchain_openai import AzureChatOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from flask import (Flask, redirect, render_template, request,
                   send_from_directory, url_for, jsonify)

app = Flask(__name__)

# Azure OpenAI
azure_endpoint = os.environ['AZURE_OPENAI_ENDPOINT']
azure_deployment = os.environ['AZURE_OPENAI_DEPLOYMENT_NAME']
model_name = os.environ['OPENAI_MODEL_NAME']
api_version = os.environ['AZURE_OPENAI_API_VERSION']

def get_database_connection(connection_string=None):
    """Create and return a database connection using the provided connection string."""
    if not connection_string:
        connection_string = os.environ.get("AZURE_SQL_CONNSTRING")
        if not connection_string:
            raise ValueError("AZURE_SQL_CONNSTRING environment variable not set.")
    
    try:
        return pyodbc.connect(connection_string)
    except pyodbc.Error as ex:
        logger.error(f"Failed to connect to database: {ex}")
        raise

def perform_vector_search(user_message, max_results=5, min_score=4, min_text_length=50, 
                          keyword=None, exclude_anonymous=True):
    """
    Perform a hybrid vector search in the database.
    
    Args:
        user_message (str): User query to embed and search against
        max_results (int): Maximum number of results to return
        min_score (int): Minimum review score to include
        min_text_length (int): Minimum text length to include
        keyword (str, optional): Specific keyword to filter for
        exclude_anonymous (bool): Whether to exclude anonymous users
    
    Returns:
        list: List of search results containing score, summary, text, and distance
    """
    results = []
    
    try:
        # Establish database connection
        cnxn = get_database_connection()
        cursor = cnxn.cursor()
        
        # Build SQL query with parameterized filters
        sql = """
            DECLARE @e VECTOR(1536);
            EXEC dbo.GET_EMBEDDINGS @model = 'text-embedding-ada-002', @text = ?, @embedding = @e OUTPUT;
            
            SELECT TOP(?)
                f.Score,
                f.Summary,
                f.Text,
                VECTOR_DISTANCE('cosine', @e, VectorBinary) AS Distance,
                CASE
                    WHEN LEN(f.Text) > 100 THEN 'Detailed Review'
                    ELSE 'Short Review'
                END AS ReviewLength,
                CASE
                    WHEN f.Score >= 4 THEN 'High Score'
                    WHEN f.Score BETWEEN 2 AND 3 THEN 'Medium Score'
                    ELSE 'Low Score'
                END AS ScoreCategory
            FROM finefoodembeddings10k$ f
            WHERE 1=1
        """
        
        params = [user_message, max_results]
        
        # Add conditional WHERE clauses
        if exclude_anonymous:
            sql += " AND f.UserId NOT LIKE 'Anonymous%'"
            
        if min_score > 0:
            sql += " AND f.Score >= ?"
            params.append(min_score)
            
        if min_text_length > 0:
            sql += " AND LEN(f.Text) > ?"
            params.append(min_text_length)
            
        if keyword:
            sql += " AND f.Text LIKE ?"
            params.append(f'%{keyword}%')
            
        # Add ORDER BY clause
        sql += """
            ORDER BY
                Distance,
                f.Score DESC,
                ReviewLength DESC;
        """
        
        # Execute the query with parameters
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        
        for row in rows:
            result = {
                'score': row[0],
                'summary': row[1],
                'text': row[2],
                'distance': row[3],
                'review_length': row[4],
                'score_category': row[5]
            }
            results.append(result)
            logger.info(f"Found result with score: {result['score']}, distance: {result['distance']}")
            
    except Exception as e:
        logger.error(f"Error performing vector search: {e}")
        raise
    finally:
        if 'cursor' in locals() and cursor:
            cursor.close()
        if 'cnxn' in locals() and cnxn:
            cnxn.close()
            
    return results

def get_llm_response(query, context=None):
    """Get response from Azure OpenAI with optional context"""
    try:
        token_provider = get_bearer_token_provider(
            DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
        )

        llm = AzureChatOpenAI(
            api_version=api_version,
            azure_deployment=azure_deployment,
            azure_endpoint=azure_endpoint,
            model_name=model_name,
            azure_ad_token_provider=token_provider
        )
        
        # If we have context from vector search, include it in the prompt
        if context:
            prompt = f"""Based on the following information:
            
{context}

Answer the user's question: {query}"""
        else:
            prompt = query
            
        return llm.invoke(prompt).content
    except Exception as e:
        logger.error(f"Error getting LLM response: {e}")
        raise

@app.route('/')
def index():
    logger.info('Request for index page received')
    return render_template('index.html')

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'),
                               'favicon.ico', mimetype='image/vnd.microsoft.icon')

@app.route('/hello', methods=['POST'])
def hello():
    user_query = request.form.get('req')
    
    try:
        if user_query:
            logger.info(f'Processing query: {user_query}')
            
            # First, try to get relevant context from vector search
            try:
                search_results = perform_vector_search(
                    user_message=user_query,
                    max_results=3  # Limit to top 3 results for context
                )
                
                # Format search results as context
                if search_results:
                    context = "\n\n".join([
                        f"Review (Score: {r['score']}/5): {r['text']}" 
                        for r in search_results
                    ])
                    logger.info(f"Found {len(search_results)} relevant results for context")
                else:
                    context = None
                    logger.info("No relevant context found from vector search")
                    
                # Get response from LLM with context if available
                response = get_llm_response(user_query, context)
                
            except Exception as db_error:
                # If vector search fails, fall back to regular LLM response
                logger.warning(f"Vector search failed, falling back to standard LLM: {db_error}")
                response = get_llm_response(user_query)
            
            return render_template('hello.html', req=response)
        else:
            logger.info('Request received with no query -- redirecting')
            return redirect(url_for('index'))
            
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        return render_template('error.html', error=str(e))

@app.route('/api/search', methods=['POST'])
def api_search():
    """API endpoint for vector search"""
    try:
        data = request.json
        if not data or 'query' not in data:
            return jsonify({'error': 'Missing query parameter'}), 400
            
        user_query = data['query']
        keyword = data.get('keyword')
        min_score = data.get('min_score', 4)
        max_results = data.get('max_results', 5)
        
        results = perform_vector_search(
            user_message=user_query,
            keyword=keyword,
            min_score=min_score,
            max_results=max_results
        )
        
        return jsonify({'results': results})
    except Exception as e:
        logger.error(f"API error: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)