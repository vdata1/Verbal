import subprocess
import json

# Command to run
command1 = ["fandango", "fuzz", "-f", "regex.fan", "-n", "1000"]
command2 = ["fandango", "fuzz", "-f", "regex2.fan", "-n", "1000"]
command3 = ["fandango", "fuzz", "-f", "regex10.fan", "-n", "1000"]
command4 = ["fandango", "fuzz", "-f", "regex20.fan", "-n", "1000"]
command5 = ["fandango", "fuzz", "-f", "regex50.fan", "-n", "1000"]
command6 = ["fandango", "fuzz", "-f", "regex100.fan", "-n", "1000"]

valid_list = []
invalid_list = []

result1 = subprocess.run(command1, capture_output=True, text=True, check=True)
result2 = subprocess.run(command2, capture_output=True, text=True, check=True)
result3 = subprocess.run(command3, capture_output=True, text=True, check=True)
result4 = subprocess.run(command4, capture_output=True, text=True, check=True)
result5 = subprocess.run(command5, capture_output=True, text=True, check=True)
result6 = subprocess.run(command6, capture_output=True, text=True, check=True)

regex_list1 = result1.stdout.strip().splitlines()
regex_list2 = result2.stdout.strip().splitlines()
regex_list3 = result3.stdout.strip().splitlines()
regex_list4 = result4.stdout.strip().splitlines()
regex_list5 = result5.stdout.strip().splitlines()
regex_list6 = result6.stdout.strip().splitlines()

try:

    #while True:

        # Split output into a list of lines
      
        # Print or use the list
        #count = 0
        print("Starting 1st ingest")
        for i in regex_list1:
            node_result = subprocess.run(['node', 'valid.js', i], capture_output=True)
    
            if node_result.returncode == 0:
                #count += 1
                #print(count)
                valid_list.append(i)
                #if len(valid_list) >= 500:
                    #print("Entered here 2")
                    
        with open("valid_regex.json", "w") as f_valid:
            json.dump(valid_list, f_valid, indent=2)
            print(len(valid_list))
                    

        print("Starting 2nd ingest")
        for i in regex_list2:
            node_result = subprocess.run(['node', 'valid.js', i], capture_output=True)
    
            if node_result.returncode == 0:
                #count += 1
                #print(count)
                valid_list.append(i)
                #if len(valid_list) >= 500:
                    #print("Entered here 2")
                    
        with open("valid_regex.json", "w") as f_valid:
            json.dump(valid_list, f_valid, indent=2)
            print(len(valid_list))


        print("Starting 3rd ingest")
        for i in regex_list3:
            node_result = subprocess.run(['node', 'valid.js', i], capture_output=True)
    
            if node_result.returncode == 0:
                #count += 1
                #print(count)
                valid_list.append(i)
                #if len(valid_list) >= 500:
                    #print("Entered here 2")
                    
        with open("valid_regex.json", "w") as f_valid:
            json.dump(valid_list, f_valid, indent=2)
            print(len(valid_list))

        print("Starting 4th ingest")
        for i in regex_list4:
            node_result = subprocess.run(['node', 'valid.js', i], capture_output=True)
    
            if node_result.returncode == 0:
                #count += 1
                #print(count)
                valid_list.append(i)
                #if len(valid_list) >= 500:
                    #print("Entered here 2")
                    
        with open("valid_regex.json", "w") as f_valid:
            json.dump(valid_list, f_valid, indent=2)
            print(len(valid_list))

    
        print("Starting 5th ingest")
        for i in regex_list5:
            node_result = subprocess.run(['node', 'valid.js', i], capture_output=True)
    
            if node_result.returncode == 0:
                #count += 1
                #print(count)
                valid_list.append(i)
                #if len(valid_list) >= 500:
                    #print("Entered here 2")
                    
        with open("valid_regex.json", "w") as f_valid:
            json.dump(valid_list, f_valid, indent=2)
            print(len(valid_list))

        print("Starting 6th ingest")
        for i in regex_list6:
            node_result = subprocess.run(['node', 'valid.js', i], capture_output=True)
    
            if node_result.returncode == 0:
                #count += 1
                #print(count)
                valid_list.append(i)
                #if len(valid_list) >= 500:
                    #print("Entered here 2")
                    
        with open("valid_regex.json", "w") as f_valid:
            json.dump(valid_list, f_valid, indent=2)
            print(len(valid_list))

except subprocess.CalledProcessError as e:
    print("Error occurred:")
    print(e.stderr)
