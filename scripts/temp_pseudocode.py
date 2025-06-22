from controller import create_env_manager

def pseudo_code() -> None:
    env = create_env_manager("docker_build")
    time.sleep(10)

    for i, url in enumerate(islice(cycle(URLS), 100)):
        
        request_url(url):
                
        sid = env.snapshot()
        container = env.create_env_from_snapshot(sid)
            
        time.sleep(0.7)  # Time B
            
    env.cleanup()


# [0] Request took 22 ms
# [1] Request took 19 ms
# [2] Request took 19 ms
# [3] Request took 19 ms
# [4] Request took 19 ms
# [5] Request took 19 ms
# [6] Request took 19 ms
# [7] Request took 19 ms
# [8] Request took 19 ms
# [9] Request took 19 ms












