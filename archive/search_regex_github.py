import requests
import re
import json

OUTPUT_FILE = "regex_harvest.json"
MIN_STARS = 2000
MAX_REPOS = 1000

def get_repos_with_stars(min_stars, max_repos):
    url = f"https://api.github.com/search/repositories?q=stars:>={min_stars}&sort=stars"
    resp = requests.get(url)
    if resp.status_code != 200:
        return []
    items = resp.json().get("items", [])
    repos = []
    for repo in items[:max_repos]:
        repos.append({
            "name": repo["full_name"],
            "url": repo["html_url"],
            "default_branch": repo["default_branch"]
        })
    return repos

def get_repo_files(repo_full_name, branch):
    url = f"https://api.github.com/repos/{repo_full_name}/git/trees/{branch}?recursive=1"
    resp = requests.get(url)
    if resp.status_code != 200:
        return []
    tree = resp.json().get("tree", [])
    return [item["path"] for item in tree if item["type"] == "blob" and item["path"].endswith(('.py', '.js', '.java', '.rb', '.go', '.ts'))]

def get_file_content(repo_full_name, file_path, branch):
    url = f"https://raw.githubusercontent.com/{repo_full_name}/{branch}/{file_path}"
    resp = requests.get(url)
    if resp.status_code == 200:
        return resp.text
    return ""

def extract_regex_strings(code):
    regex_patterns = [
        #r're\.compile\(\s*[rR]?["\'](.*?)[\"\']\s*\)',  # Python
        #r'Pattern\.compile\(\s*["\'](.*?)[\"\']\s*\)',  # Java
        r'/([^/\\]*(?:\\.[^/\\]*)*)/[gimsuy]*',          # JS/TS
        r'new RegExp\(\s*[\'"](.*?)[\'"]\s*\)',          # JS/TS
        #r'/(?P<pattern>.*?)/[gimsuy]*',                   # Ruby
        #r'regexp\.New\(\s*[\'"](.*?)[\'"]\s*\)',        # Go
        #r'/([^/\\]*(?:\\.[^/\\]*)*)/[gimsuy]*'           # General /.../ patterns
        #r're\.search\(\s*[rR]?["\'](.*?)[\"\']\s*\)',      # Python re.search
        #r're\.match\(\s*[rR]?["\'](.*?)[\"\']\s*\)',       # Python re.match
        #r're\.findall\(\s*[rR]?["\'](.*?)[\"\']\s*\)',     # Python re.findall
        #r're\.fullmatch\(\s*[rR]?["\'](.*?)[\"\']\s*\)',   # Python re.fullmatch
        #r're\.sub\(\s*[rR]?["\'](.*?)[\"\']\s*\)',         # Python re.sub
        #r're\.split\(\s*[rR]?["\'](.*?)[\"\']\s*\)',       # Python re.split
        #r're\.finditer\(\s*[rR]?["\'](.*?)[\"\']\s*\)',    # Python re.finditer
        r'/([^/\\]*(?:\\.[^/\\]*)*)/[gimsuy]*',            # JS/TS regex literal
        r'new RegExp\(\s*[\'"](.*?)[\'"]\s*,?\s*[\'"]?[gimsuy]*[\'"]?\s*\)', # JS/TS new RegExp with flags
        r'RegExp\(\s*[\'"](.*?)[\'"]\s*,?\s*[\'"]?[gimsuy]*[\'"]?\s*\)',     # JS/TS RegExp() function
        r'\.replace\(\s*/(.*?)/[gimsuy]*\s*,',             # JS/TS .replace with regex
        r'\.match\(\s*/(.*?)/[gimsuy]*\s*\)',              # JS/TS .match with regex
        r'\.test\(\s*/(.*?)/[gimsuy]*\s*\)',               # JS/TS .test with regex
        #r'/(?P<pattern>.*?)/[gimsuy]*',                    # Ruby regex literal
        # JS/TS regex patterns
        r'/([^/\\]*(?:\\.[^/\\]*)*)/[gimsuy]*',                        # regex literal
        r'new RegExp\(\s*[\'"](.*?)[\'"]\s*,?\s*[\'"]?[gimsuy]*[\'"]?\s*\)', # new RegExp('pattern', 'flags')
        r'RegExp\(\s*[\'"](.*?)[\'"]\s*,?\s*[\'"]?[gimsuy]*[\'"]?\s*\)',     # RegExp('pattern', 'flags')
        r'\.replace\(\s*/(.*?)/[gimsuy]*\s*,',                        # .replace(/pattern/, ...)
        r'\.match\(\s*/(.*?)/[gimsuy]*\s*\)',                         # .match(/pattern/)
        r'\.test\(\s*/(.*?)/[gimsuy]*\s*\)',                          # .test(/pattern/)
        r'\.split\(\s*/(.*?)/[gimsuy]*\s*\)',                         # .split(/pattern/)
        r'\.search\(\s*/(.*?)/[gimsuy]*\s*\)',                        # .search(/pattern/)
        r'\.exec\(\s*/(.*?)/[gimsuy]*\s*\)',                          # .exec(/pattern/)
        r'const\s+\w+\s*=\s*/(.*?)/[gimsuy]*',                        # const r = /pattern/
        r'let\s+\w+\s*=\s*/(.*?)/[gimsuy]*',                          # let r = /pattern/
        r'var\s+\w+\s*=\s*/(.*?)/[gimsuy]*',                          # var r = /pattern/
        r'=\s*/(.*?)/[gimsuy]*',                                      # assignment to regex literal
        r'function\s+\w+\s*\(.*?\)\s*{[^}]*?/(.*?)/[gimsuy]*',        # regex literal inside function
        r'if\s*\(.*?/(.*?)/[gimsuy]*.*?\)',                           # regex literal inside if condition
        r'while\s*\(.*?/(.*?)/[gimsuy]*.*?\)',                        # regex literal inside while condition
        r'for\s*\(.*?/(.*?)/[gimsuy]*.*?\)',                          # regex literal inside for condition
        r'/([^/\\]*(?:\\.[^/\\]*)*)/u',                           # regex literal with /.../u
        r'new RegExp\(\s*[\'"](.*?)[\'"]\s*,\s*[\'"]u[\'"]\s*\)', # new RegExp('pattern', 'u')
        r'RegExp\(\s*[\'"](.*?)[\'"]\s*,\s*[\'"]u[\'"]\s*\)',     # RegExp('pattern', 'u')
    ]   
    found = []
    for pat in regex_patterns:
        matches = re.findall(pat, code)
        # If match is a tuple (from multiple groups), take the first non-empty group
        for match in matches:
            if isinstance(match, tuple):
                for m in match:
                    if m:
                        found.append(m)
                        break
            else:
                found.append(match)
    return found

def main():
    repos = get_repos_with_stars(MIN_STARS, MAX_REPOS)
    results = []
    for repo in repos:
        print(f"Scanning {repo['name']}")
        files = get_repo_files(repo['name'], repo['default_branch'])
        repo_result = {
            "repo": repo['name'],
            "repo_url": repo['url'],
            "regexes": []
        }
        for file_path in files:
            code = get_file_content(repo['name'], file_path, repo['default_branch'])
            regexes = extract_regex_strings(code)
            for regex in regexes:
                repo_result["regexes"].append({
                    "pattern": regex,
                    "path": file_path
                })
        results.append(repo_result)
        with open(OUTPUT_FILE, "w") as f:
         json.dump(results, f, indent=2)

if __name__ == "__main__":
    main()
