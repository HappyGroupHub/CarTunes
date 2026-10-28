"use client"

import {Card, CardContent} from "@/components/ui/card"
import {Badge} from "@/components/ui/badge"
import {User, Users} from "lucide-react"
import type {RoomMember} from "@/types/room"

interface MemberListProps {
    members: RoomMember[]
    currentUserId: string
}

export function MemberList({members, currentUserId}: MemberListProps) {
    return (
        <Card className="bg-white/10 backdrop-blur-sm border-white/20">
            <CardContent className="p-4">
                <h3 className="text-white font-semibold mb-4 flex items-center">
                    <Users className="h-4 w-4 mr-2" strokeWidth={2}/>
                    房間成員 ({members.length})
                </h3>

                <div className="space-y-2">
                    {members.map((member) => (
                        <div key={member.user_id}
                             className="flex items-center space-x-3 p-2 bg-white/5 rounded">
                            <User className="h-4 w-4 text-white/60" strokeWidth={2}/>
                            <span className="text-white">{member.user_name}</span>
                            {member.user_id === currentUserId && (
                                <Badge variant="secondary" className="bg-white/20 text-white text-xs">
                                    您
                                </Badge>
                            )}
                        </div>
                    ))}
                </div>
            </CardContent>
        </Card>
    )
}
