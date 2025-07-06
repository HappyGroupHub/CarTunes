"""
Main entry point to run both FastAPI servers simultaneously
- app.py: Main API server and WebSocket server (port 5000)
- line_bot.py: LINE Bot webhook server (port 5001)
"""

import multiprocessing
import sys

import uvicorn

import utilities as utils


def run_main_app():
    """Run the main FastAPI app (app.py)"""
    config = utils.read_config()
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=config['api_endpoints_port'],
        reload=False
    )


def run_line_bot():
    """Run the LINE Bot FastAPI app (line_bot.py)"""
    import asyncio
    from line_bot import cleanup_all_rich_menus, setup_default_rich_menu, app as line_app
    config = utils.read_config()

    # Delete all existing rich menus and set up the default one
    async def setup():
        await cleanup_all_rich_menus()
        await setup_default_rich_menu()

    asyncio.run(setup())

    uvicorn.run(
        line_app,
        host="0.0.0.0",
        port=config['line_webhook_port'],
        reload=False
    )


def main():
    """Main function to start both servers"""
    config = utils.read_config()

    print("Starting CarTunes Backend Services...")
    print(f"🚀 Main API Server will run on port {config['api_endpoints_port']}")
    print(f"🤖 LINE Bot Server will run on port {config['line_webhook_port']}")
    print("\n")

    # Create processes for both servers
    main_app_process = multiprocessing.Process(target=run_main_app, name="MainAPI")
    line_bot_process = multiprocessing.Process(target=run_line_bot, name="LINEBot")

    try:
        # Start both processes
        main_app_process.start()
        line_bot_process.start()

        print("✅ Both servers started successfully!")
        print(f"📡 Main API: http://localhost:{config['api_endpoints_port']}")
        print(f"🤖 LINE Bot: http://localhost:{config['line_webhook_port']}")
        print("\nPress Ctrl+C to stop all services...\n")

        # Wait for both processes to complete
        main_app_process.join()
        line_bot_process.join()

    except KeyboardInterrupt:
        print("\n🛑 Stopping all services...")

        # Terminate both processes
        if main_app_process.is_alive():
            main_app_process.terminate()
            main_app_process.join()

        if line_bot_process.is_alive():
            line_bot_process.terminate()
            line_bot_process.join()

        print("✅ All services stopped successfully!")

    except Exception as e:
        print(f"❌ Error occurred: {e}")

        # Clean up processes
        if main_app_process.is_alive():
            main_app_process.terminate()
            main_app_process.join()

        if line_bot_process.is_alive():
            line_bot_process.terminate()
            line_bot_process.join()

        sys.exit(1)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
