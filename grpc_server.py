import os
from concurrent import futures

import grpc
from grpc_reflection.v1alpha import reflection

import hello_pb2
import hello_pb2_grpc


class HelloService(hello_pb2_grpc.HelloServiceServicer):
    def SayHello(self, request, context):
        env_name = os.getenv("RUN_ENV", "unknown")
        return hello_pb2.HelloReply(message=f"hello {env_name} from gRPC, {request.name}!")


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    hello_pb2_grpc.add_HelloServiceServicer_to_server(HelloService(), server)

    # Enable server reflection for grpcurl / grpc_cli discovery
    service_names = (
        hello_pb2.DESCRIPTOR.services_by_name["HelloService"].full_name,
        reflection.SERVICE_NAME,
    )
    reflection.enable_server_reflection(service_names, server)

    server.add_insecure_port("[::]:50051")
    print("gRPC server listening on port 50051")
    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
