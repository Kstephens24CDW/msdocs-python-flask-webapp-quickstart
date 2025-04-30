import os
# Azure OpenAI
from langchain_openai import AzureChatOpenAI
# OpenAI
from langchain_openai import ChatOpenAI

from flask import (Flask, redirect, render_template, request,
                   send_from_directory, url_for)

app = Flask(__name__)

from azure.identity import DefaultAzureCredential, get_bearer_token_provider

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
# Azure OpenAI
azure_endpoint = os.environ['AZURE_OPENAI_ENDPOINT']
azure_deployment = os.environ['AZURE_OPENAI_DEPLOYMENT_NAME']
model_name = os.environ['OPENAI_MODEL_NAME']
api_version = os.environ['AZURE_OPENAI_API_VERSION']
# Only needed if you're not using a managed identity
#api_key = os.environ['openaikey']

# OpenAI
# api_key = os.environ['OPENAI_API_KEY']

@app.route('/')
def index():
   print('Request for index page received')
   return render_template('index.html')

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'),
                               'favicon.ico', mimetype='image/vnd.microsoft.icon')

@app.route('/hello', methods=['POST'])
def hello():
    req = request.form.get('req')

    # Azure OpenAI
    llm = AzureChatOpenAI(
        azure_endpoint=azure_endpoint,
        azure_deployment=azure_deployment,
        model_name=model_name,
        api_version=api_version,
        #api_key=openaikey
    )
    text = llm.invoke(req).content

    # OpenAI
    #llm = ChatOpenAI(openai_api_key=api_key)
    #text = llm.invoke(req).content

    if req:
        print('Request for hello page received with req=%s' % req)
        return render_template('hello.html', req=text)
    else:
        print('Request for hello page received with no name or blank name -- redirecting')
        return redirect(url_for('index'))

if __name__ == '__main__':
    app.run()