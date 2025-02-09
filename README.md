# Ordelo AI Agent Chatbot

This project is a Python-based AI agent built with Langchain and FastAPI. It is designed to power a simple chatbot for Ordelo, a on-demand delivery service for restaurants that utilizes its own fleet of drivers.

## Overview

Ordelo streamlines the delivery process using the following sequence of events:

1. **Order Placement:** A customer places a delivery order.
2. **Pricing Model:** The system runs a pricing model to generate a delivery code for the order.
3. **Customer Confirmation:** The customer reviews and either accepts or rejects the provided pricing/delivery offer.
4. **Delivery Request:** If accepted, a delivery request is sent out to available delivery drivers.
5. **Live Delivery:** When a driver accepts the delivery request, the order transitions into a live delivery state.
6. **Delivery Completion:** After the delivery is successfully completed, the status is marked as complete.

## Recommended Naming Conventions for Services

For clarity and maintainability, it is recommended to adopt consistent and descriptive naming for the main services. Here are several best practices:

- **Use Descriptive Service Names:** Include the word 'Service' as a suffix to clearly indicate the role of each component.

  Examples:
  - `OrderPlacementService` – Handles receiving and validating customer orders.
  - `PricingService` – Runs the pricing model and generates delivery codes.
  - `ConfirmationService` – Manages customer acceptance or rejection of pricing/delivery offers.
  - `DispatchService` – Sends out delivery requests to available drivers.
  - `LiveDeliveryService` – Oversees the active delivery process once a driver has accepted.
  - `CompletionService` – Updates and manages the finalization of the delivery process.

- **Consider Domain-Specific Prefixes:** If your project may grow to include multiple domains, prefix your service names (e.g., `DeliveryOrderService`).

- **Follow CamelCase or PascalCase:** Using a consistent case format, such as CamelCase or PascalCase, improves readability.

## Project Structure

The repository is organized as follows:

- `main.py` - The entry point of the FastAPI application.
- `services/` - Contains the service modules such as order placement, pricing, confirmation, dispatch, live delivery, and completion.
- `models/` - Defines data models used across the application.
- `requirements.txt` - Lists project dependencies.

## Running the Project

1. Install the dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Start the FastAPI server:
   ```bash
   uvicorn main:app --reload
   ```

## Conclusion

This project integrates advanced AI capabilities to streamline and manage the full cycle of a delivery order, from placement to completion. The recommended naming conventions help ensure that the codebase remains organized, scalable, and easy to understand as the project grows.
