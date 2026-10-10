import os
import time
import torch
from dotenv import load_dotenv

# Try importing OpenAI, but don't crash if it's missing (robustness)
try:
    from openai import OpenAI
    HAS_OPENAI_LIB = True
except ImportError:
    HAS_OPENAI_LIB = False

# Local model imports
from transformers import AutoModelForCausalLM, AutoTokenizer

class LLM:
    """
    Robust LLM class that supports both OpenAI (Cloud) and Local (HuggingFace) models.
    Defaults to OpenAI if OPENAI_API_KEY is found, otherwise falls back to local.
    """

    def __init__(self, tokens: int = 500):
        """
        Initializes the LLM. 
        - Checks for OPENAI_API_KEY.
        - If present, sets up OpenAI client.
        - If missing, loads local model with GPU acceleration (CUDA/MPS).
        """
        load_dotenv() # Load environment variables from .env file
        self.tokens = tokens
        self.api_key = os.getenv("OPENAI_API_KEY")
        
        # Determine Provider
        if self.api_key and HAS_OPENAI_LIB:
            self.provider = "openai"
            self.client = OpenAI(api_key=self.api_key)
            self.model_name = "gpt-4o-mini" # Fast, cheap, smart
            print(f"🚀 LLM Provider: OpenAI ({self.model_name})")
        else:
            self.provider = "local"
            self._init_local_model()

    def _init_local_model(self):
        """
        Initializes the local model only if needed (Lazy Loading).
        Optimized for Mac (MPS) and NVIDIA (CUDA).
        """
        if torch.cuda.is_available():
            self.device = "cuda"
        elif torch.backends.mps.is_available():
            self.device = "mps" # Apple Metal Performance Shaders
        else:
            self.device = "cpu"
            
        self.model_name = "ibm-granite/granite-4.0-h-350M"
        
        print(f"💻 LLM Provider: Local ({self.model_name}) on {self.device.upper()}")

        self.tokenizer = AutoTokenizer.from_pretrained(
            self.model_name, 
            cache_dir=os.path.join(os.path.dirname(__file__), '.hf_cache')
        )
        
        # Load model with correct device mapping
        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_name, 
            device_map=self.device,
            torch_dtype=torch.float16 if self.device != "cpu" else "auto"
        )
        self.model.eval()

    def generate(self, context: str, prompt: str) -> str:
        """
        Generates text using the selected provider.
        """
        if self.provider == "openai":
            return self._generate_openai(context, prompt)
        else:
            return self._generate_local(context, prompt)

    def _generate_openai(self, context: str, prompt: str) -> str:
        start = time.time()
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": context},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=self.tokens,
                temperature=0.7
            )
            output = response.choices[0].message.content.strip()
            end = time.time()
            print(f"⚡ OpenAI generated in {end - start:.4f} seconds")
            return output
        except Exception as e:
            print(f"❌ OpenAI Error: {e}. Falling back to Local...")
            # Runtime fallback: If internet drops or key fails, init local and retry
            self.provider = "local"
            self._init_local_model()
            return self._generate_local(context, prompt)

    def _generate_local(self, context: str, prompt: str) -> str:
        start = time.time()
        
        chat = [
            {"role": "system", "content": context},
            {"role": "user", "content": prompt},
        ]
        
        # Apply chat template
        try:
            text = self.tokenizer.apply_chat_template(chat, tokenize=False, add_generation_prompt=True)
        except Exception:
            # Fallback for models without chat templates
            text = f"{context}\n\nUser: {prompt}\n\nAssistant:"

        input_tokens = self.tokenizer([text], return_tensors="pt").to(self.device)

        with torch.no_grad():
            output_ids = self.model.generate(
                **input_tokens, 
                max_new_tokens=self.tokens
            )
            
        # Decode only the new tokens
        output_ids = [
            out[len(inp):] for inp, out in zip(input_tokens.input_ids, output_ids)
        ]
        output = self.tokenizer.batch_decode(output_ids, skip_special_tokens=True)[0]
        
        end = time.time()
        print(f"🐢 Local Model generated in {end - start:.4f} seconds")
        return output